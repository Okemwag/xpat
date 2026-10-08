"""Self-service registration: set up a new organisation (as its administrator) or ask to join an existing one (as a user).

Security model:
- Nobody becomes an administrator of an existing organisation by registering. "Set up a new organisation" creates a new,
  empty organisation whose owner is the registrant. "Join" only creates a *request*; an administrator of that organisation
  approves it and chooses the roles.
- Every registration is confirmed by a link e-mailed to the address first. Until then the account cannot sign in and no
  administrator sees a request, so nobody can claim someone else's work address.
- Requests are routed only to organisations whose `allowed_domains` setting contains the e-mail's domain. Public mail
  domains (gmail.com …) never route anywhere.
- The response is the same whether or not an account or a matching organisation exists (no enumeration); the e-mail says
  what happened. Attempts are rate-limited per address and per network address, and audited.
- Self-registration is on by default outside production; in production set FLOODCAT_ALLOW_SIGNUP=1 to allow it.
"""

import os
from datetime import timedelta
from sqlalchemy import func, select
from ..core.errors import ModelError
from . import audit, email as mail, security
from .db import (
    invitations,
    memberships,
    now,
    one_time_tokens,
    organisations,
    uid,
    users,
)
from .identity import (
    DEFAULT_SETTINGS,
    VERIFY_TTL,
    _email,
    auth_url,
    rate_limit,
    settings_for,
)
from .rbac import require, validate_roles

PUBLIC_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "ymail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "mail.com",
    "zoho.com",
    "yandex.com",
}
KINDS = ("org", "join")
OWNER_ROLES = [
    "owner",
    "head_uw",
]  # the founder administers the organisation and can use it straight away


def signup_enabled():
    default = "0" if os.getenv("FLOODCAT_ENV") == "production" else "1"
    return os.getenv("FLOODCAT_ALLOW_SIGNUP", default) == "1"


def _domain(email_addr):
    return email_addr.rsplit("@", 1)[1]


def _matching_orgs(conn, domain):
    if domain in PUBLIC_DOMAINS:
        return []
    rows = conn.execute(
        select(
            organisations.c.id, organisations.c.name, organisations.c.settings
        ).where(organisations.c.status.in_(("active", "trial")))
    ).mappings()
    return [
        {"id": r["id"], "name": r["name"]}
        for r in rows
        if domain
        in [
            d.lower().lstrip("@")
            for d in {**DEFAULT_SETTINGS, **(r["settings"] or {})}["allowed_domains"]
        ]
    ]


def start(conn, kind, email_addr, display_name, password, org_name="", request=None):
    """Begin a registration. Raises only for problems the person must fix (password, missing name, rate limit)."""
    if not signup_enabled():
        raise ModelError(
            "signup_off",
            "Registration is closed. Ask your administrator for an invitation.",
        )
    if kind not in KINDS:
        raise ModelError(
            "invalid_kind", "Choose whether to set up a new organisation or join one"
        )
    email_addr = _email(email_addr)
    display_name = " ".join(str(display_name or "").split())[:120]
    org_name = " ".join(str(org_name or "").split())[:200]
    if not display_name:
        raise ModelError("invalid_name", "Enter your name")
    if kind == "org" and not org_name:
        raise ModelError("invalid_org", "Enter your organisation's name")
    ip = (request or {}).get("ip") or "unknown"
    rate_limit(
        conn,
        f"signup-ip:{ip}",
        10,
        timedelta(hours=1),
        "Too many registrations from your network; try again later",
    )
    rate_limit(
        conn,
        f"signup:{email_addr}",
        3,
        timedelta(hours=1),
        "Too many attempts for this address; try again later",
    )
    security.check_password(password, email_addr, (display_name, org_name))
    user = (
        conn.execute(select(users).where(users.c.email == email_addr))
        .mappings()
        .first()
    )
    if user and user["status"] == "active":
        mail.send(
            conn,
            email_addr,
            "You already have an Xpat account",
            [
                "Someone (probably you) tried to register this address again. You already have an account: sign in, or reset your "
                "password if you have forgotten it. If this was not you, you can ignore this e-mail."
            ],
            ("Sign in", f"{auth_url()}/auth/login"),
            kind="signup_existing",
        )
        audit.record(
            conn,
            "auth.signup_started",
            target_type="user",
            target_id=user["id"],
            details={"kind": kind, "existing": True},
            outcome="ignored",
            request=request,
        )
        return
    if (
        user and user["status"] != "unverified"
    ):  # deactivated or anonymised: say nothing, change nothing
        audit.record(
            conn,
            "auth.signup_started",
            target_type="user",
            target_id=user["id"],
            details={"kind": kind, "existing": True},
            outcome="denied",
            request=request,
        )
        return
    if user:
        user_id = user["id"]
        conn.execute(
            users.update()
            .where(users.c.id == user_id)
            .values(
                display_name=display_name,
                password_hash=security.hash_password(password),
            )
        )
    else:
        user_id = uid()
        conn.execute(
            users.insert().values(
                id=user_id,
                email=email_addr,
                display_name=display_name,
                password_hash=security.hash_password(password),
                status="unverified",
                created_at=now(),
            )
        )
    conn.execute(
        one_time_tokens.update()
        .where(
            one_time_tokens.c.user_id == user_id,
            one_time_tokens.c.kind == "signup",
            one_time_tokens.c.used_at.is_(None),
        )
        .values(used_at=now())
    )
    raw, token_hash = security.new_token()
    conn.execute(
        one_time_tokens.insert().values(
            id=uid(),
            kind="signup",
            user_id=user_id,
            token_hash=token_hash,
            data={"kind": kind, "org_name": org_name},
            created_at=now(),
            expires_at=now() + VERIFY_TTL,
        )
    )
    what = (
        f"set up {org_name} on Xpat, with you as its administrator"
        if kind == "org"
        else "ask to join your organisation on Xpat; an administrator there will approve you and choose your access"
    )
    mail.send(
        conn,
        email_addr,
        "Confirm your e-mail to finish registering on Xpat",
        [
            f"Confirm this address to {what}.",
            "The link works once and expires in 24 hours. If you did not register, ignore this e-mail.",
        ],
        ("Confirm my e-mail", f"{auth_url()}/auth/register/confirm/{raw}"),
        kind="signup_confirm",
    )
    audit.record(
        conn,
        "auth.signup_started",
        target_type="user",
        target_id=user_id,
        details={"kind": kind},
        request=request,
    )


def confirm(conn, raw, request=None):
    """Finish a registration from the e-mailed link.

    Returns {'user_id', 'kind', 'org_id' (new organisation, or None), 'requested': [organisation names]}.
    """
    row = (
        conn.execute(
            select(one_time_tokens).where(
                one_time_tokens.c.token_hash == security.hash_token(raw or ""),
                one_time_tokens.c.kind == "signup",
            )
        )
        .mappings()
        .first()
    )
    from .identity import _aware

    if not row or row["used_at"] or _aware(row["expires_at"]) < now():
        raise ModelError(
            "invalid_token",
            "This link is invalid or has expired. Register again to get a new one.",
        )
    user = (
        conn.execute(select(users).where(users.c.id == row["user_id"]))
        .mappings()
        .first()
    )
    if not user or user["status"] not in ("unverified", "active"):
        raise ModelError("account_inactive", "This account is not active")
    conn.execute(
        one_time_tokens.update()
        .where(one_time_tokens.c.id == row["id"])
        .values(used_at=now())
    )
    conn.execute(
        users.update()
        .where(users.c.id == user["id"])
        .values(status="active", email_verified_at=now())
    )
    kind, domain = row["data"].get("kind"), _domain(user["email"])
    if kind == "org":
        org_id = uid()
        name = row["data"].get("org_name") or f"{user['display_name']}'s organisation"
        conn.execute(
            organisations.insert().values(
                id=org_id,
                name=name,
                status="trial",
                plan="trial",
                seats=10,
                created_at=now(),
                trial_ends_at=now() + timedelta(days=60),
                settings={
                    **DEFAULT_SETTINGS,
                    "allowed_domains": [] if domain in PUBLIC_DOMAINS else [domain],
                },
                profile={},
            )
        )
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=org_id,
                user_id=user["id"],
                roles=list(OWNER_ROLES),
                status="active",
                created_at=now(),
            )
        )
        audit.record(
            conn,
            "org.self_registered",
            actor=None,
            org_id=org_id,
            target_type="organisation",
            target_id=org_id,
            details={"name": name, "owner": user["id"]},
            request=request,
        )
        return {"user_id": user["id"], "kind": kind, "org_id": org_id, "requested": []}
    requested = []
    from .data import notify_role

    for org in _matching_orgs(conn, domain):
        exists = conn.execute(
            select(memberships.c.id).where(
                memberships.c.org_id == org["id"], memberships.c.user_id == user["id"]
            )
        ).scalar()
        if exists:
            continue
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=org["id"],
                user_id=user["id"],
                roles=[],
                status="pending",
                created_at=now(),
            )
        )
        for role in ("owner", "admin"):
            notify_role(
                conn,
                org["id"],
                role,
                "join_request",
                f"{user['display_name']} ({user['email']}) asked to join. Review it in Users & invitations.",
            )
        audit.record(
            conn,
            "user.join_requested",
            org_id=org["id"],
            target_type="user",
            target_id=user["id"],
            request=request,
        )
        requested.append(org["name"])
    if not requested:
        mail.send(
            conn,
            user["email"],
            "No Xpat organisation uses your e-mail domain yet",
            [
                f"Your address is confirmed, but no organisation on Xpat accepts members from {domain}.",
                "Ask your administrator to invite you, or set up a new organisation for your team.",
            ],
            ("Set up an organisation", f"{auth_url()}/auth/register?kind=org"),
            kind="signup_no_org",
        )
    return {"user_id": user["id"], "kind": kind, "org_id": None, "requested": requested}


def pending_orgs(conn, user_id):
    """Names of organisations where this person's request is waiting for approval (for the sign-in message)."""
    return [
        r.name
        for r in conn.execute(
            select(organisations.c.name)
            .join(memberships, memberships.c.org_id == organisations.c.id)
            .where(memberships.c.user_id == user_id, memberships.c.status == "pending")
        )
    ]


def list_requests(conn, principal):
    require(principal, "users.manage")
    q = (
        select(
            users.c.id, users.c.email, users.c.display_name, memberships.c.created_at
        )
        .join(memberships, memberships.c.user_id == users.c.id)
        .where(
            memberships.c.org_id == principal.org_id, memberships.c.status == "pending"
        )
        .order_by(memberships.c.created_at)
    )
    return [dict(r) for r in conn.execute(q).mappings()]


def decide(conn, principal, user_id, approve, roles=None, request=None):
    """An administrator approves (with roles) or declines a request to join."""
    require(principal, "users.manage")
    m = (
        conn.execute(
            select(memberships).where(
                memberships.c.org_id == principal.org_id,
                memberships.c.user_id == user_id,
                memberships.c.status == "pending",
            )
        )
        .mappings()
        .first()
    )
    if not m:
        raise ModelError("not_found", "No pending request from this person")
    user = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    org = (
        conn.execute(
            select(organisations).where(organisations.c.id == principal.org_id)
        )
        .mappings()
        .first()
    )
    if not approve:
        conn.execute(memberships.delete().where(memberships.c.id == m["id"]))
        mail.send(
            conn,
            user["email"],
            f"Your request to join {org['name']} on Xpat",
            [
                f"An administrator of {org['name']} did not approve your request. Contact them if you think this is a mistake."
            ],
            kind="join_declined",
        )
        audit.record(
            conn,
            "user.join_declined",
            actor=principal,
            target_type="user",
            target_id=user_id,
            request=request,
        )
        return None
    roles = validate_roles(roles)
    if "owner" in roles and "owner" not in principal.roles:
        raise ModelError("forbidden", "Only an owner can grant the owner role")
    active = conn.execute(
        select(func.count())
        .select_from(memberships)
        .where(
            memberships.c.org_id == principal.org_id, memberships.c.status == "active"
        )
    ).scalar()
    invited = conn.execute(
        select(func.count())
        .select_from(invitations)
        .where(
            invitations.c.org_id == principal.org_id,
            invitations.c.accepted_at.is_(None),
            invitations.c.revoked_at.is_(None),
            invitations.c.expires_at > now(),
        )
    ).scalar()
    if active + invited >= org["seats"]:
        raise ModelError(
            "seat_limit",
            f"All {org['seats']} seats are in use; remove a user or upgrade the plan",
        )
    conn.execute(
        memberships.update()
        .where(memberships.c.id == m["id"])
        .values(status="active", roles=roles)
    )
    mail.send(
        conn,
        user["email"],
        f"You can now use Xpat at {org['name']}",
        [f"An administrator approved your request. Your access: {', '.join(roles)}."],
        ("Sign in", f"{auth_url()}/auth/login"),
        kind="join_approved",
    )
    from .data import notify

    notify(
        conn,
        principal.org_id,
        user_id,
        "join_approved",
        f"Welcome — your roles are: {', '.join(roles)}",
    )
    audit.record(
        conn,
        "user.join_approved",
        actor=principal,
        target_type="user",
        target_id=user_id,
        details={"roles": roles},
        request=request,
    )
    return roles
