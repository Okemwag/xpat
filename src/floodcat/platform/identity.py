"""Identity: accounts, organisations membership, authentication, sessions, MFA, account flows, API tokens.

Implements AUTH-07…17, FLOW-01…10, SEC-06 of docs/ORGANISATION_CHECKLIST.md. Every state change writes an audit
event in the same transaction.
"""

import os
from datetime import timedelta
from sqlalchemy import and_, func, or_, select, update
from ..core.errors import ModelError
from . import audit, email as mail, security
from .db import (
    api_tokens,
    invitations,
    login_attempts,
    memberships,
    now,
    one_time_tokens,
    organisations,
    recovery_codes,
    sessions,
    team_members,
    users,
    uid,
)
from .rbac import ASSIGNABLE, PERMISSIONS, Principal, require, validate_roles

DEFAULT_SETTINGS = {
    "mfa_policy": "admins",
    "session_idle_minutes": 30,
    "session_max_hours": 12,
    "allowed_domains": [],
    "ai_mode": "full",
    "retention_runs_days": 730,
    "retention_audit_days": 2555,
    "default_assumption_set_id": None,
    "authority_limit_loss_kes": None,
    "authority_limit_tiv_kes": None,
    "default_visibility": "team",
    "enforce_separation_of_duties": True,
    # AI model choice (ai/llm.choose): allowed providers, organisation default, client data kept on this server,
    # and each member's own preference {user_id: provider} (set only through orgs.set_ai_preference).
    "ai_providers": ["gemini", "ollama"],
    "ai_default_provider": None,
    "ai_local_for_client_data": False,
    "ai_preferences": {},
}
ADMIN_ROLES = {"owner", "admin"}
INVITE_TTL = timedelta(hours=72)
RESET_TTL = timedelta(minutes=30)
VERIFY_TTL = timedelta(hours=24)
LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILURES_ACCOUNT = 5
MAX_FAILURES_IP = 30
REAUTH_WINDOW = timedelta(minutes=10)
TOUCH_INTERVAL = timedelta(seconds=60)


def app_url():
    return os.getenv("FLOODCAT_APP_URL", "http://localhost:8501").rstrip("/")


def auth_url():
    return os.getenv("FLOODCAT_AUTH_URL", "http://localhost:8000").rstrip("/")


def _email(value):
    value = str(value or "").strip().lower()
    if (
        "@" not in value
        or len(value) > 320
        or value.startswith("@")
        or "." not in value.split("@")[-1]
        or " " in value
    ):
        raise ModelError("invalid_email", "Enter a valid e-mail address")
    return value


def _aware(dt):
    from datetime import timezone

    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def settings_for(conn, org_id):
    row = conn.execute(
        select(organisations.c.settings).where(organisations.c.id == org_id)
    ).scalar()
    return {**DEFAULT_SETTINGS, **(row or {})}


# Rate limiting (AUTH-09, SEC-05) --------------------------------------------------------------------------
def rate_count(conn, key, window, failures_only=True):
    q = (
        select(func.count())
        .select_from(login_attempts)
        .where(login_attempts.c.key == key, login_attempts.c.at >= now() - window)
    )
    if failures_only:
        q = q.where(login_attempts.c.success.is_(False))
    return conn.execute(q).scalar()


def rate_hit(conn, key, success=False):
    conn.execute(login_attempts.insert().values(key=key, at=now(), success=success))


def rate_limit(conn, key, limit, window, message="Too many requests; try again later"):
    if rate_count(conn, key, window, failures_only=False) >= limit:
        raise ModelError("rate_limited", message)
    rate_hit(conn, key, success=True)


# Principals ----------------------------------------------------------------------------------------
def principal_for(conn, user_id, org_id, session_id=None, support=False):
    user = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    if not user or user["status"] != "active":
        return None
    roles, teams = (), ()
    if org_id:
        m = (
            conn.execute(
                select(memberships).where(
                    memberships.c.org_id == org_id, memberships.c.user_id == user_id
                )
            )
            .mappings()
            .first()
        )
        if m and m["status"] == "active":
            roles = tuple(m["roles"])
            teams = tuple(
                r[0]
                for r in conn.execute(
                    select(team_members.c.team_id).where(
                        team_members.c.user_id == user_id
                    )
                )
            )
        elif not (support and user["is_platform_admin"]):
            return None
    return Principal(
        user_id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        org_id=org_id,
        roles=roles,
        team_ids=teams,
        is_platform_admin=bool(user["is_platform_admin"]),
        session_id=session_id,
        support_access=support,
        extra={
            "mfa_enabled": user["mfa_enabled_at"] is not None,
            "email_verified": user["email_verified_at"] is not None,
        },
    )


def user_orgs(conn, user_id):
    q = (
        select(
            organisations.c.id,
            organisations.c.name,
            organisations.c.status,
            memberships.c.roles,
        )
        .join(memberships, memberships.c.org_id == organisations.c.id)
        .where(
            memberships.c.user_id == user_id,
            memberships.c.status == "active",
            organisations.c.status != "closed",
        )
    )
    return [dict(r) for r in conn.execute(q).mappings()]


# Organisations and first users ---------------------------------------------------------------------
def create_organisation(
    conn,
    actor,
    name,
    owner_email,
    owner_name="",
    settings=None,
    profile=None,
    plan="pilot",
    seats=10,
    request=None,
):
    """Platform admin creates an organisation and invites its first owner (ADM-09)."""
    if actor is not None:
        require(actor, "platform.manage")
    name = str(name or "").strip()
    if not name:
        raise ModelError("invalid_org", "Organisation name required")
    org_id = uid()
    conn.execute(
        organisations.insert().values(
            id=org_id,
            name=name[:200],
            status="trial",
            plan=plan,
            seats=seats,
            created_at=now(),
            trial_ends_at=now() + timedelta(days=60),
            settings={**DEFAULT_SETTINGS, **(settings or {})},
            profile=profile or {},
        )
    )
    audit.record(
        conn,
        "org.created",
        actor=actor,
        org_id=org_id,
        target_type="organisation",
        target_id=org_id,
        details={"name": name},
        request=request,
    )
    raw = _invite(
        conn, actor, org_id, owner_email, ["owner"], [], request, check_domain=False
    )
    return org_id, raw


def bootstrap_platform_admin(conn, email, display_name, password):
    """Create the first platform admin (Xpat staff) if none exists. Used by `flood-cat create-platform-admin`."""
    if conn.execute(
        select(func.count())
        .select_from(users)
        .where(users.c.is_platform_admin.is_(True))
    ).scalar():
        raise ModelError("exists", "A platform admin already exists")
    email = _email(email)
    security.check_password(password, email)
    user_id = uid()
    conn.execute(
        users.insert().values(
            id=user_id,
            email=email,
            display_name=display_name or email,
            password_hash=security.hash_password(password),
            email_verified_at=now(),
            status="active",
            created_at=now(),
            is_platform_admin=True,
        )
    )
    audit.record(conn, "platform.admin_created", target_type="user", target_id=user_id)
    return user_id


# Invitations (FLOW-01) -----------------------------------------------------------------------------
def _invite(
    conn, actor, org_id, email_addr, roles, team_ids, request, check_domain=True
):
    email_addr = _email(email_addr)
    roles = validate_roles(roles)
    org = (
        conn.execute(select(organisations).where(organisations.c.id == org_id))
        .mappings()
        .first()
    )
    if not org or org["status"] in ("suspended", "closed"):
        raise ModelError("org_inactive", "The organisation is not active")
    domains = [
        d.lower().lstrip("@") for d in settings_for(conn, org_id)["allowed_domains"]
    ]
    if check_domain and domains and email_addr.split("@")[1] not in domains:
        raise ModelError(
            "domain_not_allowed",
            f"Only addresses at {', '.join(domains)} can join this organisation",
        )
    active = conn.execute(
        select(func.count())
        .select_from(memberships)
        .where(memberships.c.org_id == org_id, memberships.c.status == "active")
    ).scalar()
    pending = conn.execute(
        select(func.count())
        .select_from(invitations)
        .where(
            invitations.c.org_id == org_id,
            invitations.c.accepted_at.is_(None),
            invitations.c.revoked_at.is_(None),
            invitations.c.expires_at > now(),
        )
    ).scalar()
    if active + pending >= org["seats"]:
        raise ModelError(
            "seat_limit",
            f"All {org['seats']} seats are in use; remove a user or upgrade the plan",
        )
    existing = conn.execute(
        select(memberships.c.status)
        .join(users, users.c.id == memberships.c.user_id)
        .where(memberships.c.org_id == org_id, users.c.email == email_addr)
    ).scalar()
    if existing == "active":
        raise ModelError("already_member", "This person is already a member")
    conn.execute(
        invitations.update()
        .where(
            invitations.c.org_id == org_id,
            invitations.c.email == email_addr,
            invitations.c.accepted_at.is_(None),
            invitations.c.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    raw, token_hash = security.new_token()
    invite_id = uid()
    conn.execute(
        invitations.insert().values(
            id=invite_id,
            org_id=org_id,
            email=email_addr,
            roles=roles,
            team_ids=list(team_ids or []),
            token_hash=token_hash,
            invited_by=getattr(actor, "user_id", None),
            created_at=now(),
            expires_at=now() + INVITE_TTL,
        )
    )
    mail.send(
        conn,
        email_addr,
        f"You're invited to {org['name']} on Xpat",
        [
            f"{getattr(actor, 'display_name', 'An administrator')} invited you to join {org['name']} on Xpat as {', '.join(roles)}.",
            "The link expires in 72 hours and can be used once.",
        ],
        ("Accept invitation", f"{auth_url()}/auth/invite/{raw}"),
        kind="invitation",
    )
    audit.record(
        conn,
        "user.invited",
        actor=actor,
        org_id=org_id,
        target_type="invitation",
        target_id=invite_id,
        details={"email": email_addr, "roles": roles},
        request=request,
    )
    return raw


def invite(conn, principal, email_addr, roles, team_ids=(), request=None):
    require(principal, "users.manage")
    if "owner" in roles and "owner" not in principal.roles:
        raise ModelError("forbidden", "Only an owner can invite another owner")
    return _invite(
        conn, principal, principal.org_id, email_addr, roles, team_ids, request
    )


def revoke_invitation(conn, principal, invite_id, request=None):
    require(principal, "users.manage")
    n = conn.execute(
        invitations.update()
        .where(
            invitations.c.id == invite_id,
            invitations.c.org_id == principal.org_id,
            invitations.c.accepted_at.is_(None),
        )
        .values(revoked_at=now())
    ).rowcount
    if not n:
        raise ModelError("not_found", "Invitation not found")
    audit.record(
        conn,
        "user.invitation_revoked",
        actor=principal,
        target_type="invitation",
        target_id=invite_id,
        request=request,
    )


def list_invitations(conn, principal):
    require(principal, "users.manage")
    q = (
        select(invitations)
        .where(
            invitations.c.org_id == principal.org_id,
            invitations.c.accepted_at.is_(None),
            invitations.c.revoked_at.is_(None),
        )
        .order_by(invitations.c.created_at.desc())
    )
    return [
        {k: v for k, v in r.items() if k != "token_hash"}
        | {"expired": _aware(r["expires_at"]) < now()}
        for r in conn.execute(q).mappings()
    ]


def invitation_for(conn, raw):
    row = (
        conn.execute(
            select(invitations, organisations.c.name.label("org_name"))
            .join(organisations, organisations.c.id == invitations.c.org_id)
            .where(invitations.c.token_hash == security.hash_token(raw))
        )
        .mappings()
        .first()
    )
    if (
        not row
        or row["accepted_at"]
        or row["revoked_at"]
        or _aware(row["expires_at"]) < now()
    ):
        raise ModelError(
            "invalid_token",
            "This invitation link is invalid or has expired. Ask your administrator for a new one.",
        )
    has_account = (
        conn.execute(
            select(users.c.id).where(
                users.c.email == row["email"], users.c.status != "unverified"
            )
        ).scalar()
        is not None
    )
    return {**dict(row), "has_account": has_account}


def accept_invitation(
    conn,
    raw,
    display_name=None,
    password=None,
    existing_password=None,
    sso_user_id=None,
    request=None,
):
    """New users set a name and password; existing users confirm with their current password (or are already SSO-authenticated)."""
    inv = invitation_for(conn, raw)
    user = (
        conn.execute(select(users).where(users.c.email == inv["email"]))
        .mappings()
        .first()
    )
    if user and user["status"] == "unverified":
        # Registered but never confirmed: the invitation link proves the address, so finish the account here.
        name = str(display_name or "").strip() or user["display_name"]
        if not sso_user_id:
            security.check_password(password, inv["email"], (name, inv["org_name"]))
        conn.execute(
            users.update()
            .where(users.c.id == user["id"])
            .values(
                display_name=name[:120],
                password_hash=None if sso_user_id else security.hash_password(password),
                status="active",
                email_verified_at=now(),
            )
        )
        user_id = user["id"]
    elif user:
        if user["status"] != "active":
            raise ModelError("account_inactive", "This account is not active")
        if sso_user_id != user["id"]:
            ok, _ = security.verify_password(
                user["password_hash"], existing_password or ""
            )
            if not ok:
                raise ModelError(
                    "bad_credentials",
                    "Confirm the invitation with your current Xpat password",
                )
        user_id = user["id"]
    else:
        name = str(display_name or "").strip()
        if not name:
            raise ModelError("invalid_name", "Enter your name")
        org_name = inv["org_name"]
        if not sso_user_id:
            security.check_password(password, inv["email"], (name, org_name))
        user_id = uid()
        conn.execute(
            users.insert().values(
                id=user_id,
                email=inv["email"],
                display_name=name[:120],
                password_hash=None if sso_user_id else security.hash_password(password),
                email_verified_at=now(),
                status="active",
                created_at=now(),
            )
        )
    member = conn.execute(
        select(memberships.c.id).where(
            memberships.c.org_id == inv["org_id"], memberships.c.user_id == user_id
        )
    ).scalar()
    if member:
        conn.execute(
            memberships.update()
            .where(memberships.c.id == member)
            .values(roles=inv["roles"], status="active", deactivated_at=None)
        )
    else:
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=inv["org_id"],
                user_id=user_id,
                roles=inv["roles"],
                status="active",
                created_at=now(),
            )
        )
    for team_id in inv["team_ids"] or []:
        if not conn.execute(
            select(team_members).where(
                team_members.c.team_id == team_id, team_members.c.user_id == user_id
            )
        ).first():
            conn.execute(team_members.insert().values(team_id=team_id, user_id=user_id))
    conn.execute(
        invitations.update()
        .where(invitations.c.id == inv["id"])
        .values(accepted_at=now())
    )
    audit.record(
        conn,
        "user.invitation_accepted",
        org_id=inv["org_id"],
        target_type="user",
        target_id=user_id,
        details={"roles": inv["roles"], "new_account": user is None},
        request=request,
    )
    return user_id, inv["org_id"]


# Authentication (AUTH-09) --------------------------------------------------------------------------
def authenticate(conn, email_addr, password, request=None):
    """Return the user row. Generic errors, per-account and per-IP throttling, timing-equalised for unknown accounts."""
    ip = (request or {}).get("ip") or "unknown"
    try:
        email_addr = _email(email_addr)
    except ModelError:
        email_addr = str(email_addr or "").strip().lower()[:320]
    if (
        rate_count(conn, f"login:{email_addr}", LOGIN_WINDOW) >= MAX_FAILURES_ACCOUNT
        or rate_count(conn, f"login-ip:{ip}", LOGIN_WINDOW) >= MAX_FAILURES_IP
    ):
        audit.record(
            conn,
            "auth.login_blocked",
            target_type="user",
            details={"email": email_addr},
            outcome="denied",
            request=request,
        )
        raise ModelError(
            "locked",
            "Too many failed attempts. Wait 15 minutes, or reset your password.",
        )
    user = (
        conn.execute(select(users).where(users.c.email == email_addr))
        .mappings()
        .first()
    )
    ok, rehash = (
        security.verify_password(user["password_hash"], password)
        if user and user["password_hash"]
        else (security.dummy_verify() or False, False)
    )
    if not user or not ok or user["status"] != "active":
        rate_hit(conn, f"login:{email_addr}")
        rate_hit(conn, f"login-ip:{ip}")
        audit.record(
            conn,
            "auth.login_failed",
            target_type="user",
            target_id=user["id"] if user else None,
            details={
                "email": email_addr,
                "reason": "inactive" if user and ok else "bad_credentials",
            },
            outcome="denied",
            request=request,
        )
        raise ModelError("bad_credentials", "E-mail or password is incorrect")
    if rehash:
        conn.execute(
            users.update()
            .where(users.c.id == user["id"])
            .values(password_hash=security.hash_password(password))
        )
    rate_hit(conn, f"login:{email_addr}", success=True)
    conn.execute(
        login_attempts.delete().where(
            login_attempts.c.key == f"login:{email_addr}",
            login_attempts.c.success.is_(False),
        )
    )
    return dict(user)


def mfa_required(conn, user, org_id):
    """Whether this user must use MFA in this organisation (AUTH-10)."""
    if user["is_platform_admin"]:
        return True
    if not org_id:
        return user["mfa_enabled_at"] is not None
    policy = settings_for(conn, org_id)["mfa_policy"]
    roles = (
        conn.execute(
            select(memberships.c.roles).where(
                memberships.c.org_id == org_id, memberships.c.user_id == user["id"]
            )
        ).scalar()
        or []
    )
    return (
        policy == "all"
        or (policy == "admins" and bool(ADMIN_ROLES & set(roles)))
        or user["mfa_enabled_at"] is not None
    )


def verify_second_factor(conn, user_id, code, request=None):
    user = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    if not user or not user["mfa_secret_enc"] or not user["mfa_enabled_at"]:
        return False
    if rate_count(conn, f"mfa:{user_id}", LOGIN_WINDOW) >= MAX_FAILURES_ACCOUNT:
        raise ModelError("locked", "Too many wrong codes. Wait 15 minutes.")
    code = str(code or "").strip()
    if security.verify_totp(security.decrypt(user["mfa_secret_enc"]), code):
        return True
    hashed = security.hash_token(code.lower())
    row = conn.execute(
        select(recovery_codes.c.id).where(
            recovery_codes.c.user_id == user_id,
            recovery_codes.c.code_hash == hashed,
            recovery_codes.c.used_at.is_(None),
        )
    ).scalar()
    if row:
        conn.execute(
            recovery_codes.update()
            .where(recovery_codes.c.id == row)
            .values(used_at=now())
        )
        audit.record(
            conn,
            "auth.recovery_code_used",
            target_type="user",
            target_id=user_id,
            request=request,
        )
        return True
    rate_hit(conn, f"mfa:{user_id}")
    audit.record(
        conn,
        "auth.mfa_failed",
        target_type="user",
        target_id=user_id,
        outcome="denied",
        request=request,
    )
    return False


# Sessions (AUTH-13…17) -----------------------------------------------------------------------------
def start_session(
    conn, user_id, org_id, method="password", mfa_passed=False, request=None
):
    s = settings_for(conn, org_id) if org_id else DEFAULT_SETTINGS
    raw, token_hash = security.new_token()
    session_id = uid()
    conn.execute(
        sessions.insert().values(
            id=session_id,
            token_hash=token_hash,
            user_id=user_id,
            org_id=org_id,
            created_at=now(),
            last_seen_at=now(),
            expires_at=now() + timedelta(hours=s["session_max_hours"]),
            method=method,
            mfa_passed=mfa_passed,
            reauth_at=now(),
            ip=(request or {}).get("ip"),
            user_agent=((request or {}).get("user_agent") or "")[:300],
        )
    )
    conn.execute(
        users.update().where(users.c.id == user_id).values(last_login_at=now())
    )
    audit.record(
        conn,
        "auth.login",
        org_id=org_id,
        target_type="user",
        target_id=user_id,
        details={"method": method, "mfa": mfa_passed},
        request=request,
    )
    return raw, session_id


def resolve_session(conn, raw, touch=True):
    """Return (Principal, state) for a session cookie, or (None, reason). Enforces expiry, idle timeout, user and membership status."""
    if not raw:
        return None, "none"
    row = (
        conn.execute(
            select(sessions).where(sessions.c.token_hash == security.hash_token(raw))
        )
        .mappings()
        .first()
    )
    if not row or row["revoked_at"]:
        return None, "revoked"
    t = now()
    s = settings_for(conn, row["org_id"]) if row["org_id"] else DEFAULT_SETTINGS
    if _aware(row["expires_at"]) < t or _aware(row["last_seen_at"]) < t - timedelta(
        minutes=s["session_idle_minutes"]
    ):
        conn.execute(
            sessions.update().where(sessions.c.id == row["id"]).values(revoked_at=t)
        )
        audit.record(
            conn,
            "auth.session_expired",
            org_id=row["org_id"],
            target_type="session",
            target_id=row["id"],
        )
        return None, "expired"
    support = False
    principal = principal_for(conn, row["user_id"], row["org_id"], row["id"])
    if principal is None and row["org_id"]:
        from .orgs import active_support_grant

        if active_support_grant(conn, row["org_id"], row["user_id"]):
            principal = principal_for(
                conn, row["user_id"], row["org_id"], row["id"], support=True
            )
            support = True
    if principal is None:
        conn.execute(
            sessions.update().where(sessions.c.id == row["id"]).values(revoked_at=t)
        )
        return None, "revoked"
    user = (
        conn.execute(select(users).where(users.c.id == row["user_id"]))
        .mappings()
        .first()
    )
    if (
        user["mfa_enabled_at"] is not None
        and not row["mfa_passed"]
        and row["method"] != "sso"
    ):
        return None, "mfa_pending"
    needs_mfa_setup = (
        mfa_required(conn, user, row["org_id"])
        and user["mfa_enabled_at"] is None
        and row["method"] != "sso"
    )
    org_status = (
        conn.execute(
            select(organisations.c.status).where(organisations.c.id == row["org_id"])
        ).scalar()
        if row["org_id"]
        else None
    )
    if touch and _aware(row["last_seen_at"]) < t - TOUCH_INTERVAL:
        conn.execute(
            sessions.update().where(sessions.c.id == row["id"]).values(last_seen_at=t)
        )
    extra = {
        **principal.extra,
        "mfa_setup_required": needs_mfa_setup,
        "org_status": org_status,
        "read_only": org_status == "suspended",
        "reauth_at": row["reauth_at"],
        "method": row["method"],
        "support_access": support,
    }
    return Principal(**{**principal.__dict__, "extra": extra}), "ok"


def pending_session(conn, raw):
    """(session row, user row) for a session waiting for its second factor."""
    row = (
        conn.execute(
            select(sessions).where(
                sessions.c.token_hash == security.hash_token(raw or "")
            )
        )
        .mappings()
        .first()
    )
    if (
        not row
        or row["revoked_at"]
        or _aware(row["expires_at"]) < now()
        or row["mfa_passed"]
    ):
        return None, None
    return row, conn.execute(
        select(users).where(users.c.id == row["user_id"])
    ).mappings().first()


def complete_mfa(conn, raw, code, request=None):
    row, user = pending_session(conn, raw)
    if not row:
        raise ModelError("invalid_session", "Your sign-in expired; start again")
    if not verify_second_factor(conn, user["id"], code, request):
        raise ModelError("bad_code", "That code did not match")
    conn.execute(
        sessions.update()
        .where(sessions.c.id == row["id"])
        .values(mfa_passed=True, last_seen_at=now(), reauth_at=now())
    )
    audit.record(
        conn,
        "auth.mfa_passed",
        org_id=row["org_id"],
        target_type="user",
        target_id=user["id"],
        request=request,
    )


def revoke_session(conn, principal, session_id, request=None):
    n = conn.execute(
        sessions.update()
        .where(
            sessions.c.id == session_id,
            sessions.c.user_id == principal.user_id,
            sessions.c.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    ).rowcount
    if n:
        audit.record(
            conn,
            "auth.session_revoked",
            actor=principal,
            target_type="session",
            target_id=session_id,
            request=request,
        )
    return n


def revoke_all_sessions(
    conn, user_id, except_session=None, reason="", actor=None, request=None
):
    q = sessions.update().where(
        sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None)
    )
    if except_session:
        q = q.where(sessions.c.id != except_session)
    n = conn.execute(q.values(revoked_at=now())).rowcount
    if n:
        audit.record(
            conn,
            "auth.sessions_revoked",
            actor=actor,
            target_type="user",
            target_id=user_id,
            details={"count": n, "reason": reason},
            request=request,
        )
    return n


def logout(conn, raw, request=None):
    row = (
        conn.execute(
            select(sessions).where(
                sessions.c.token_hash == security.hash_token(raw or "")
            )
        )
        .mappings()
        .first()
    )
    if row and not row["revoked_at"]:
        conn.execute(
            sessions.update().where(sessions.c.id == row["id"]).values(revoked_at=now())
        )
        audit.record(
            conn,
            "auth.logout",
            org_id=row["org_id"],
            target_type="user",
            target_id=row["user_id"],
            request=request,
        )


def list_sessions(conn, principal):
    q = (
        select(
            sessions.c.id,
            sessions.c.created_at,
            sessions.c.last_seen_at,
            sessions.c.ip,
            sessions.c.user_agent,
            sessions.c.method,
            sessions.c.org_id,
        )
        .where(
            sessions.c.user_id == principal.user_id,
            sessions.c.revoked_at.is_(None),
            sessions.c.expires_at > now(),
        )
        .order_by(sessions.c.last_seen_at.desc())
    )
    return [
        dict(r) | {"current": r["id"] == principal.session_id}
        for r in conn.execute(q).mappings()
    ]


def switch_org(conn, raw, org_id, request=None):
    row = (
        conn.execute(
            select(sessions).where(sessions.c.token_hash == security.hash_token(raw))
        )
        .mappings()
        .first()
    )
    if not row or principal_for(conn, row["user_id"], org_id) is None:
        raise ModelError("forbidden", "Not a member of that organisation")
    conn.execute(
        sessions.update().where(sessions.c.id == row["id"]).values(org_id=org_id)
    )
    audit.record(
        conn,
        "auth.org_switched",
        org_id=org_id,
        target_type="user",
        target_id=row["user_id"],
        request=request,
    )


def reauthenticate(conn, principal, password=None, code=None, request=None):
    """Step-up before sensitive actions (AUTH-17): password, or an MFA code for SSO users."""
    user = (
        conn.execute(select(users).where(users.c.id == principal.user_id))
        .mappings()
        .first()
    )
    ok = False
    if password and user["password_hash"]:
        ok, _ = security.verify_password(user["password_hash"], password)
    if not ok and code:
        ok = verify_second_factor(conn, principal.user_id, code, request)
    if not ok:
        rate_hit(conn, f"reauth:{principal.user_id}")
        audit.record(
            conn,
            "auth.reauth_failed",
            actor=principal,
            target_type="user",
            target_id=principal.user_id,
            outcome="denied",
            request=request,
        )
        raise ModelError("bad_credentials", "That did not match. Try again.")
    conn.execute(
        sessions.update()
        .where(sessions.c.id == principal.session_id)
        .values(reauth_at=now())
    )
    audit.record(
        conn,
        "auth.reauthenticated",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )


def require_recent_auth(conn, principal):
    at = conn.execute(
        select(sessions.c.reauth_at).where(sessions.c.id == principal.session_id)
    ).scalar()
    if not at or _aware(at) < now() - REAUTH_WINDOW:
        raise ModelError("reauth_required", "Confirm your password to continue")


# Password flows (FLOW-03, FLOW-04) ------------------------------------------------------------------
def forgot_password(conn, email_addr, request=None):
    """Always behaves the same whether or not the account exists (no enumeration)."""
    ip = (request or {}).get("ip") or "unknown"
    try:
        email_addr = _email(email_addr)
    except ModelError:
        return
    try:
        rate_limit(conn, f"reset:{email_addr}", 3, timedelta(hours=1))
        rate_limit(conn, f"reset-ip:{ip}", 20, timedelta(hours=1))
    except ModelError:
        audit.record(
            conn,
            "auth.reset_rate_limited",
            details={"email": email_addr},
            outcome="denied",
            request=request,
        )
        return
    user = (
        conn.execute(select(users).where(users.c.email == email_addr))
        .mappings()
        .first()
    )
    if not user or user["status"] != "active" or not user["password_hash"]:
        audit.record(
            conn,
            "auth.reset_requested",
            details={"email": email_addr, "account": False},
            outcome="ignored",
            request=request,
        )
        return
    conn.execute(
        one_time_tokens.update()
        .where(
            one_time_tokens.c.user_id == user["id"],
            one_time_tokens.c.kind == "password_reset",
            one_time_tokens.c.used_at.is_(None),
        )
        .values(used_at=now())
    )
    raw, token_hash = security.new_token()
    conn.execute(
        one_time_tokens.insert().values(
            id=uid(),
            kind="password_reset",
            user_id=user["id"],
            token_hash=token_hash,
            data={},
            created_at=now(),
            expires_at=now() + RESET_TTL,
        )
    )
    mail.send(
        conn,
        email_addr,
        "Reset your Xpat password",
        [
            "We received a request to reset your password.",
            "The link works once and expires in 30 minutes. If you did not ask for this, ignore this e-mail; your password is unchanged.",
        ],
        ("Choose a new password", f"{auth_url()}/auth/reset/{raw}"),
        kind="password_reset",
    )
    audit.record(
        conn,
        "auth.reset_requested",
        target_type="user",
        target_id=user["id"],
        details={"account": True},
        request=request,
    )


def _token(conn, kind, raw):
    row = (
        conn.execute(
            select(one_time_tokens).where(
                one_time_tokens.c.token_hash == security.hash_token(raw or ""),
                one_time_tokens.c.kind == kind,
            )
        )
        .mappings()
        .first()
    )
    if not row or row["used_at"] or _aware(row["expires_at"]) < now():
        raise ModelError(
            "invalid_token", "This link is invalid or has expired. Request a new one."
        )
    return row


def reset_needs_mfa(conn, raw):
    row = _token(conn, "password_reset", raw)
    return (
        conn.execute(
            select(users.c.mfa_enabled_at).where(users.c.id == row["user_id"])
        ).scalar()
        is not None
    )


def reset_password(conn, raw, new_password, code=None, request=None):
    row = _token(conn, "password_reset", raw)
    user = (
        conn.execute(select(users).where(users.c.id == row["user_id"]))
        .mappings()
        .first()
    )
    if user["mfa_enabled_at"] and not verify_second_factor(
        conn, user["id"], code, request
    ):
        raise ModelError(
            "mfa_required",
            "Enter a code from your authenticator app or a recovery code",
        )
    security.check_password(new_password, user["email"], (user["display_name"],))
    conn.execute(
        users.update()
        .where(users.c.id == user["id"])
        .values(password_hash=security.hash_password(new_password))
    )
    conn.execute(
        one_time_tokens.update()
        .where(one_time_tokens.c.id == row["id"])
        .values(used_at=now())
    )
    revoke_all_sessions(conn, user["id"], reason="password_reset", request=request)
    mail.send(
        conn,
        user["email"],
        "Your Xpat password was changed",
        [
            "Your password was reset. All your sessions were signed out.",
            "If this was not you, contact your administrator immediately.",
        ],
        kind="password_changed",
    )
    audit.record(
        conn,
        "auth.password_reset",
        target_type="user",
        target_id=user["id"],
        request=request,
    )
    return user["id"]


def change_password(conn, principal, current, new_password, request=None):
    user = (
        conn.execute(select(users).where(users.c.id == principal.user_id))
        .mappings()
        .first()
    )
    ok, _ = security.verify_password(user["password_hash"], current or "")
    if not ok:
        audit.record(
            conn,
            "auth.password_change_failed",
            actor=principal,
            target_type="user",
            target_id=user["id"],
            outcome="denied",
            request=request,
        )
        raise ModelError("bad_credentials", "Your current password is incorrect")
    security.check_password(new_password, user["email"], (user["display_name"],))
    conn.execute(
        users.update()
        .where(users.c.id == user["id"])
        .values(password_hash=security.hash_password(new_password))
    )
    revoke_all_sessions(
        conn,
        user["id"],
        except_session=principal.session_id,
        reason="password_change",
        actor=principal,
        request=request,
    )
    mail.send(
        conn,
        user["email"],
        "Your Xpat password was changed",
        [
            "Your password was changed and your other sessions were signed out.",
            "If this was not you, reset your password and contact your administrator.",
        ],
        kind="password_changed",
    )
    audit.record(
        conn,
        "auth.password_changed",
        actor=principal,
        target_type="user",
        target_id=user["id"],
        request=request,
    )


# E-mail verification and change (FLOW-02, FLOW-05) ---------------------------------------------------
def request_email_change(conn, principal, new_email, request=None):
    require_recent_auth(conn, principal)
    new_email = _email(new_email)
    if conn.execute(select(users.c.id).where(users.c.email == new_email)).scalar():
        raise ModelError(
            "email_taken", "That e-mail address is already used by another account"
        )
    raw, token_hash = security.new_token()
    conn.execute(
        one_time_tokens.insert().values(
            id=uid(),
            kind="email_change",
            user_id=principal.user_id,
            token_hash=token_hash,
            data={"new_email": new_email},
            created_at=now(),
            expires_at=now() + VERIFY_TTL,
        )
    )
    mail.send(
        conn,
        new_email,
        "Confirm your new Xpat e-mail address",
        ["Confirm this address to make it your Xpat sign-in e-mail."],
        ("Confirm e-mail address", f"{auth_url()}/auth/verify-email/{raw}"),
        kind="email_change",
    )
    mail.send(
        conn,
        principal.email,
        "Your Xpat e-mail address is being changed",
        [
            f"A request was made to change your sign-in e-mail to {new_email}. If this was not you, contact your administrator."
        ],
        kind="email_change_notice",
    )
    audit.record(
        conn,
        "user.email_change_requested",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )


def confirm_email_change(conn, raw, request=None):
    row = _token(conn, "email_change", raw)
    new_email = row["data"]["new_email"]
    if conn.execute(select(users.c.id).where(users.c.email == new_email)).scalar():
        raise ModelError("email_taken", "That e-mail address is already in use")
    conn.execute(
        users.update()
        .where(users.c.id == row["user_id"])
        .values(email=new_email, email_verified_at=now())
    )
    conn.execute(
        one_time_tokens.update()
        .where(one_time_tokens.c.id == row["id"])
        .values(used_at=now())
    )
    revoke_all_sessions(conn, row["user_id"], reason="email_changed", request=request)
    audit.record(
        conn,
        "user.email_changed",
        target_type="user",
        target_id=row["user_id"],
        request=request,
    )


def update_profile(conn, principal, display_name, request=None):
    name = str(display_name or "").strip()
    if not name:
        raise ModelError("invalid_name", "Enter your name")
    conn.execute(
        users.update()
        .where(users.c.id == principal.user_id)
        .values(display_name=name[:120])
    )
    audit.record(
        conn,
        "user.profile_updated",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )


# MFA (AUTH-10, FLOW-06) ------------------------------------------------------------------------------
def begin_mfa(conn, principal):
    secret = security.new_totp_secret()
    conn.execute(
        users.update()
        .where(users.c.id == principal.user_id)
        .values(mfa_secret_enc=security.encrypt(secret), mfa_enabled_at=None)
    )
    return secret, security.totp_uri(secret, principal.email)


def confirm_mfa(conn, principal, code, request=None):
    enc = conn.execute(
        select(users.c.mfa_secret_enc).where(users.c.id == principal.user_id)
    ).scalar()
    if not enc or not security.verify_totp(security.decrypt(enc), code):
        raise ModelError(
            "bad_code",
            "That code did not match. Check the time on your phone and try again.",
        )
    conn.execute(
        users.update()
        .where(users.c.id == principal.user_id)
        .values(mfa_enabled_at=now())
    )
    codes, hashes = security.new_recovery_codes()
    conn.execute(
        recovery_codes.delete().where(recovery_codes.c.user_id == principal.user_id)
    )
    conn.execute(
        recovery_codes.insert(),
        [{"id": uid(), "user_id": principal.user_id, "code_hash": h} for h in hashes],
    )
    if principal.session_id:
        conn.execute(
            sessions.update()
            .where(sessions.c.id == principal.session_id)
            .values(mfa_passed=True)
        )
    mail.send(
        conn,
        principal.email,
        "Two-step verification is on",
        ["Two-step verification was turned on for your Xpat account."],
        kind="mfa_enabled",
    )
    audit.record(
        conn,
        "auth.mfa_enabled",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )
    return codes


def regenerate_recovery_codes(conn, principal, request=None):
    require_recent_auth(conn, principal)
    codes, hashes = security.new_recovery_codes()
    conn.execute(
        recovery_codes.delete().where(recovery_codes.c.user_id == principal.user_id)
    )
    conn.execute(
        recovery_codes.insert(),
        [{"id": uid(), "user_id": principal.user_id, "code_hash": h} for h in hashes],
    )
    audit.record(
        conn,
        "auth.recovery_codes_regenerated",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )
    return codes


def disable_mfa(conn, principal, request=None):
    require_recent_auth(conn, principal)
    user = (
        conn.execute(select(users).where(users.c.id == principal.user_id))
        .mappings()
        .first()
    )
    if (
        any(
            mfa_required(conn, {**user, "mfa_enabled_at": None}, o["id"])
            for o in user_orgs(conn, user["id"])
        )
        or user["is_platform_admin"]
    ):
        raise ModelError(
            "mfa_required",
            "Your organisation requires two-step verification for your role",
        )
    conn.execute(
        users.update()
        .where(users.c.id == principal.user_id)
        .values(mfa_secret_enc=None, mfa_enabled_at=None)
    )
    conn.execute(
        recovery_codes.delete().where(recovery_codes.c.user_id == principal.user_id)
    )
    audit.record(
        conn,
        "auth.mfa_disabled",
        actor=principal,
        target_type="user",
        target_id=principal.user_id,
        request=request,
    )


def admin_reset_mfa(conn, principal, user_id, reason, request=None):
    """Admin-assisted reset (lost phone). Needs a reason; the user must enrol again at next sign-in."""
    require(principal, "security.manage")
    require_recent_auth(conn, principal)
    if user_id == principal.user_id:
        raise ModelError(
            "forbidden",
            "Ask another administrator to reset your own two-step verification",
        )
    if not str(reason or "").strip():
        raise ModelError(
            "reason_required", "Give a reason (e.g. support ticket number)"
        )
    _member(conn, principal.org_id, user_id)
    conn.execute(
        users.update()
        .where(users.c.id == user_id)
        .values(mfa_secret_enc=None, mfa_enabled_at=None)
    )
    conn.execute(recovery_codes.delete().where(recovery_codes.c.user_id == user_id))
    revoke_all_sessions(
        conn, user_id, reason="mfa_reset", actor=principal, request=request
    )
    audit.record(
        conn,
        "auth.mfa_reset_by_admin",
        actor=principal,
        target_type="user",
        target_id=user_id,
        details={"reason": reason},
        request=request,
    )


# Membership administration (FLOW-07, FLOW-08, RBAC) --------------------------------------------------
def _member(conn, org_id, user_id):
    m = (
        conn.execute(
            select(memberships).where(
                memberships.c.org_id == org_id, memberships.c.user_id == user_id
            )
        )
        .mappings()
        .first()
    )
    if not m:
        raise ModelError("not_found", "User not found in this organisation")
    return m


def _owners(conn, org_id):
    rows = conn.execute(
        select(memberships.c.user_id, memberships.c.roles).where(
            memberships.c.org_id == org_id, memberships.c.status == "active"
        )
    )
    return [r.user_id for r in rows if "owner" in r.roles]


def set_roles(conn, principal, user_id, roles, reason="", request=None):
    require(principal, "users.manage")
    require_recent_auth(conn, principal)
    roles = validate_roles(roles)
    m = _member(conn, principal.org_id, user_id)
    if ("owner" in roles) != ("owner" in m["roles"]) and "owner" not in principal.roles:
        raise ModelError(
            "forbidden", "Only an owner can grant or remove the owner role"
        )
    if (
        "owner" in m["roles"]
        and "owner" not in roles
        and _owners(conn, principal.org_id) == [user_id]
    ):
        raise ModelError("last_owner", "An organisation must keep at least one owner")
    if user_id == principal.user_id and not (ADMIN_ROLES & set(roles)):
        raise ModelError(
            "forbidden",
            "You cannot remove your own administrator access; ask another administrator",
        )
    conn.execute(
        memberships.update().where(memberships.c.id == m["id"]).values(roles=roles)
    )
    revoke_all_sessions(
        conn, user_id, reason="role_change", actor=principal, request=request
    )
    from .data import notify

    notify(
        conn,
        principal.org_id,
        user_id,
        "role_changed",
        f"Your roles are now: {', '.join(roles)}",
    )
    audit.record(
        conn,
        "user.roles_changed",
        actor=principal,
        target_type="user",
        target_id=user_id,
        details={"before": m["roles"], "after": roles, "reason": reason},
        request=request,
    )


def deactivate(conn, principal, user_id, reassign_to=None, request=None):
    """Leaver: access, sessions and API tokens revoked at once; their runs and submissions are re-assigned (FLOW-07)."""
    require(principal, "users.manage")
    if user_id == principal.user_id:
        raise ModelError("forbidden", "You cannot deactivate yourself")
    m = _member(conn, principal.org_id, user_id)
    if "owner" in m["roles"] and _owners(conn, principal.org_id) == [user_id]:
        raise ModelError("last_owner", "Transfer ownership first")
    conn.execute(
        memberships.update()
        .where(memberships.c.id == m["id"])
        .values(status="deactivated", deactivated_at=now())
    )
    revoke_all_sessions(
        conn, user_id, reason="deactivated", actor=principal, request=request
    )
    conn.execute(
        api_tokens.update()
        .where(
            api_tokens.c.user_id == user_id,
            api_tokens.c.org_id == principal.org_id,
            api_tokens.c.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    moved = 0
    if reassign_to:
        _member(conn, principal.org_id, reassign_to)
        from .data import reassign_owner

        moved = reassign_owner(conn, principal.org_id, user_id, reassign_to)
    audit.record(
        conn,
        "user.deactivated",
        actor=principal,
        target_type="user",
        target_id=user_id,
        details={"reassigned_to": reassign_to, "records_moved": moved},
        request=request,
    )


def reactivate(conn, principal, user_id, request=None):
    require(principal, "users.manage")
    m = _member(conn, principal.org_id, user_id)
    conn.execute(
        memberships.update()
        .where(memberships.c.id == m["id"])
        .values(status="active", deactivated_at=None)
    )
    audit.record(
        conn,
        "user.reactivated",
        actor=principal,
        target_type="user",
        target_id=user_id,
        request=request,
    )


def list_members(conn, principal):
    if not (principal.can("users.manage") or principal.can("access_review.read")):
        require(principal, "users.manage")
    q = (
        select(
            users.c.id,
            users.c.email,
            users.c.display_name,
            users.c.last_login_at,
            users.c.mfa_enabled_at,
            users.c.created_at,
            memberships.c.roles,
            memberships.c.status,
            memberships.c.deactivated_at,
        )
        .join(memberships, memberships.c.user_id == users.c.id)
        .where(memberships.c.org_id == principal.org_id)
        .order_by(users.c.display_name)
    )
    return [dict(r) for r in conn.execute(q).mappings()]


def anonymise_user(conn, principal, user_id, request=None):
    """Erase personal details after retention (FLOW-09). Audit events keep the pseudonymous user ID."""
    require(principal, "platform.manage")
    conn.execute(
        users.update()
        .where(users.c.id == user_id)
        .values(
            email=f"deleted-{user_id}@invalid",
            display_name="Deleted user",
            password_hash=None,
            mfa_secret_enc=None,
            status="anonymised",
            sso_subject=None,
        )
    )
    conn.execute(
        memberships.update()
        .where(memberships.c.user_id == user_id)
        .values(status="deactivated", deactivated_at=now())
    )
    revoke_all_sessions(
        conn, user_id, reason="anonymised", actor=principal, request=request
    )
    audit.record(
        conn,
        "user.anonymised",
        actor=principal,
        org_id=None,
        target_type="user",
        target_id=user_id,
        request=request,
    )


# API tokens (SEC-06) ------------------------------------------------------------------------------------
API_SCOPES = ("runs.create", "runs.read", "runs.export", "evidence.add", "ai.extract")


def create_api_token(conn, principal, name, scopes, days=90, request=None):
    if not (principal.can("tokens.manage") or principal.can("runs.create")):
        require(principal, "runs.create")
    scopes = [s for s in dict.fromkeys(scopes or []) if s in API_SCOPES]
    if not scopes:
        raise ModelError("invalid_scope", "Choose at least one scope")
    missing = [s for s in scopes if not principal.can(s)]
    if missing:
        raise ModelError(
            "forbidden",
            "You cannot grant scopes you do not have: " + ", ".join(missing),
        )
    if not 1 <= int(days) <= 365:
        raise ModelError("invalid_expiry", "Tokens expire after 1–365 days")
    raw = "xpat_" + security.new_token(30)[0]
    token_id = uid()
    conn.execute(
        api_tokens.insert().values(
            id=token_id,
            org_id=principal.org_id,
            user_id=principal.user_id,
            name=str(name or "API token")[:120],
            prefix=raw[:12],
            token_hash=security.hash_token(raw),
            scopes=scopes,
            created_at=now(),
            expires_at=now() + timedelta(days=int(days)),
        )
    )
    audit.record(
        conn,
        "api_token.created",
        actor=principal,
        target_type="api_token",
        target_id=token_id,
        details={"scopes": scopes, "days": days},
        request=request,
    )
    return raw


def list_api_tokens(conn, principal, all_users=False):
    q = select(
        api_tokens.c.id,
        api_tokens.c.name,
        api_tokens.c.prefix,
        api_tokens.c.scopes,
        api_tokens.c.created_at,
        api_tokens.c.expires_at,
        api_tokens.c.revoked_at,
        api_tokens.c.last_used_at,
        api_tokens.c.user_id,
    ).where(api_tokens.c.org_id == principal.org_id)
    if not (all_users and principal.can("tokens.manage")):
        q = q.where(api_tokens.c.user_id == principal.user_id)
    return [
        dict(r)
        for r in conn.execute(q.order_by(api_tokens.c.created_at.desc())).mappings()
    ]


def revoke_api_token(conn, principal, token_id, request=None):
    q = api_tokens.update().where(
        api_tokens.c.id == token_id,
        api_tokens.c.org_id == principal.org_id,
        api_tokens.c.revoked_at.is_(None),
    )
    if not principal.can("tokens.manage"):
        q = q.where(api_tokens.c.user_id == principal.user_id)
    if not conn.execute(q.values(revoked_at=now())).rowcount:
        raise ModelError("not_found", "Token not found")
    audit.record(
        conn,
        "api_token.revoked",
        actor=principal,
        target_type="api_token",
        target_id=token_id,
        request=request,
    )


def resolve_api_token(conn, raw, request=None):
    row = (
        conn.execute(
            select(api_tokens).where(
                api_tokens.c.token_hash == security.hash_token(raw or "")
            )
        )
        .mappings()
        .first()
    )
    if not row or row["revoked_at"] or _aware(row["expires_at"]) < now():
        return None
    principal = principal_for(conn, row["user_id"], row["org_id"])
    if principal is None:
        return None
    if (
        not _aware(row["last_used_at"])
        or _aware(row["last_used_at"]) < now() - TOUCH_INTERVAL
    ):
        conn.execute(
            api_tokens.update()
            .where(api_tokens.c.id == row["id"])
            .values(last_used_at=now())
        )
    # The token can do only what both its scopes and the user's roles allow.
    scoped_roles = tuple(
        r for r in principal.roles if PERMISSIONS.get(r, set()) & set(row["scopes"])
    )
    return Principal(
        **{
            **principal.__dict__,
            "roles": scoped_roles,
            "extra": {
                **principal.extra,
                "token_scopes": tuple(row["scopes"]),
                "token_id": row["id"],
            },
        }
    )


def token_allows(principal, permission):
    scopes = principal.extra.get("token_scopes")
    return principal.can(permission) and (scopes is None or permission in scopes)
