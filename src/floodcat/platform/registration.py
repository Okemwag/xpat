"""Self-service registration: set up a new organisation (as its administrator) or ask to join an existing one (as a user).

Security model:
- Nobody becomes an administrator of an existing organisation by registering. "Create an organisation" creates a new,
  empty organisation whose owner is the registrant. "Request an account" only creates a *request*; an administrator of
  that organisation approves it and chooses the roles, so a person cannot reach anyone else's data on their own.
- The account is created as soon as the form is submitted; there is no e-mail confirmation step. Administrators should
  check who is asking before approving a request (the request shows the name and e-mail address).
- Requests are routed only to organisations whose `allowed_domains` setting contains the e-mail's domain. Public mail
  domains (gmail.com …) never route anywhere.
- Attempts are rate-limited per address and per network address, and audited.
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
    organisations,
    uid,
    users,
)
from .identity import (
    DEFAULT_SETTINGS,
    _email,
    auth_url,
    rate_limit,
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


CODE_ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, so codes read out loud cleanly
)


def new_code():
    import secrets

    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _normalise_code(code):
    text = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return f"{text[:4]}-{text[4:]}" if len(text) == 8 else ""


def _org_by_code(conn, code):
    code = _normalise_code(code)
    if not code:
        return None
    for r in conn.execute(
        select(
            organisations.c.id, organisations.c.name, organisations.c.settings
        ).where(organisations.c.status.in_(("active", "trial")))
    ).mappings():
        if (r["settings"] or {}).get("join_code") == code:
            return {"id": r["id"], "name": r["name"]}
    return None


def join_code(conn, principal, regenerate=False, request=None):
    """The organisation's join code, created on first use. Administrators share it with colleagues who register."""
    require(principal, "users.manage")
    from .identity import settings_for

    current = settings_for(conn, principal.org_id)
    if current.get("join_code") and not regenerate:
        return current["join_code"]
    code = new_code()
    conn.execute(
        organisations.update()
        .where(organisations.c.id == principal.org_id)
        .values(settings={**current, "join_code": code})
    )
    audit.record(
        conn,
        "org.join_code_changed" if regenerate else "org.join_code_created",
        actor=principal,
        target_type="organisation",
        target_id=principal.org_id,
        request=request,
    )
    return code


def register(
    conn,
    kind,
    email_addr,
    display_name,
    password,
    org_name="",
    request=None,
    org_code="",
):
    """Create the account and finish registration in one step.

    Returns {'user_id', 'kind', 'org_id' (the new organisation, or None), 'requested': [organisation names]}.
    Raises ModelError for anything the person must fix (password, missing name, existing account, no matching
    organisation, rate limit); nothing is created in that case.
    """
    if not signup_enabled():
        raise ModelError(
            "signup_off",
            "Registration is closed. Ask your administrator for an invitation.",
        )
    if kind not in KINDS:
        raise ModelError(
            "invalid_kind",
            "Choose whether to create an organisation or request an account",
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
        raise ModelError(
            "account_exists",
            "An account with this e-mail already exists. Sign in instead, or reset your password.",
        )
    if (
        user and user["status"] != "unverified"
    ):  # deactivated or anonymised accounts are not reopened this way
        raise ModelError(
            "account_inactive",
            "This e-mail cannot be registered. Contact your organisation's administrator.",
        )
    domain = _domain(email_addr)
    matches = []
    if kind == "join":
        if str(org_code or "").strip():
            found = _org_by_code(conn, org_code)
            if not found:
                raise ModelError(
                    "bad_code",
                    "That organisation code was not recognised. Check it with your administrator; it looks like ABCD-EFGH.",
                )
            matches = [found]
        else:
            matches = _matching_orgs(conn, domain)
        if not matches:
            raise ModelError(
                "no_org",
                "Enter your organisation code to send your request. Your administrator finds it under "
                "Administration, Users & invitations."
                if domain in PUBLIC_DOMAINS
                else f"No organisation on Xpat accepts members from {domain} yet. Enter your organisation code "
                "(your administrator has it), or ask them to invite you.",
            )
    if user:  # left over from the earlier confirm-by-e-mail flow: finish it now
        user_id = user["id"]
        conn.execute(
            users.update()
            .where(users.c.id == user_id)
            .values(
                display_name=display_name,
                password_hash=security.hash_password(password),
                status="active",
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
                status="active",
                created_at=now(),
            )
        )
    audit.record(
        conn,
        "auth.signup",
        target_type="user",
        target_id=user_id,
        details={"kind": kind},
        request=request,
    )
    if kind == "org":
        org_id = uid()
        conn.execute(
            organisations.insert().values(
                id=org_id,
                name=org_name,
                status="trial",
                plan="trial",
                seats=10,
                created_at=now(),
                trial_ends_at=now() + timedelta(days=60),
                settings={
                    **DEFAULT_SETTINGS,
                    "allowed_domains": [] if domain in PUBLIC_DOMAINS else [domain],
                    "join_code": new_code(),
                },
                profile={},
            )
        )
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=org_id,
                user_id=user_id,
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
            details={"name": org_name, "owner": user_id},
            request=request,
        )
        return {"user_id": user_id, "kind": kind, "org_id": org_id, "requested": []}
    from .data import notify_role

    requested = []
    for org in matches:
        if conn.execute(
            select(memberships.c.id).where(
                memberships.c.org_id == org["id"], memberships.c.user_id == user_id
            )
        ).scalar():
            continue
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=org["id"],
                user_id=user_id,
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
                f"{display_name} ({email_addr}) asked to join. Review it in Users & invitations.",
            )
        audit.record(
            conn,
            "user.join_requested",
            org_id=org["id"],
            target_type="user",
            target_id=user_id,
            request=request,
        )
        requested.append(org["name"])
    return {"user_id": user_id, "kind": kind, "org_id": None, "requested": requested}


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
