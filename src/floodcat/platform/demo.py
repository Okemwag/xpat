"""Demo organisation with one ready-made account per role, for demonstrations (never in production).

`flood-cat seed-demo` (or `make seed`) creates the organisation "Kenya Re (demo)" and eight accounts — owner, admin,
head of underwriting, underwriter, analyst, reviewer, viewer and auditor — all sharing one password, verified, with
two-step verification off. Addresses use the reserved `.test` domain (RFC 2606), so nothing is ever e-mailed to them.
Accounts are created directly (like the guest route), not through invitations, so no e-mail is sent. Every step is
audited. Running it again changes nothing unless asked to reset the password.

With FLOODCAT_DEMO_LOGINS=1 the sign-in page also offers one-click sign-in as each demo role (`/auth/demo/{role}`).
Both the seed and the one-click sign-in refuse to run when FLOODCAT_ENV=production.
"""

import os
import secrets
from sqlalchemy import select
from ..core.errors import ModelError
from . import audit, identity, security
from .db import memberships, now, organisations, uid, users

DEMO_ORG = "Kenya Re (demo)"
DOMAIN = "demo.xpat.test"
ACCOUNTS = (
    ("owner", "Demo Owner"),
    ("admin", "Demo Administrator"),
    ("head_uw", "Demo Head of Underwriting"),
    ("underwriter", "Demo Underwriter"),
    ("analyst", "Demo Analyst"),
    ("reviewer", "Demo Evidence Reviewer"),
    ("viewer", "Demo Viewer"),
    ("auditor", "Demo Auditor"),
)
ROLE_LABELS = {r: n.replace("Demo ", "") for r, n in ACCOUNTS}


def email_for(role):
    return f"{role.replace('_', '-')}@{DOMAIN}"


def _production():
    return os.getenv("FLOODCAT_ENV") == "production"


def logins_enabled():
    """One-click demo sign-in: only when explicitly switched on, and never in production."""
    return os.getenv("FLOODCAT_DEMO_LOGINS") == "1" and not _production()


def new_password():
    """A memorable but strong shared password, e.g. 'river-7f3a9c-culvert' (no organisation or e-mail words)."""
    first, second = (secrets.choice(["river", "basin", "storm", "culvert", "ridge", "delta"]) for _ in range(2))
    return f"{first}-{secrets.token_hex(3)}-{second}-flood"


def demo_org_id(conn):
    return conn.execute(select(organisations.c.id).where(organisations.c.name == DEMO_ORG)).scalar()


def seed(conn, password, reset_password=False):
    """Create (or complete) the demo organisation and accounts. Returns what was created and what already existed."""
    if _production():
        raise ModelError("forbidden", "Demo accounts are never created in production (FLOODCAT_ENV=production)")
    security.check_password(password, email_for("owner"), (DEMO_ORG,))
    org_id = demo_org_id(conn)
    created_org = org_id is None
    if created_org:
        org_id = uid()
        conn.execute(
            organisations.insert().values(
                id=org_id,
                name=DEMO_ORG,
                status="active",
                plan="demo",
                seats=50,
                created_at=now(),
                settings={**identity.DEFAULT_SETTINGS, "mfa_policy": "off", "allowed_domains": [DOMAIN],
                          "default_visibility": "org"},
                profile={"country": "Kenya", "note": "Demonstration organisation; all data synthetic"},
            )
        )
        audit.record(conn, "demo.org_created", org_id=org_id, target_type="organisation", target_id=org_id,
                     details={"name": DEMO_ORG})
    created, existing, reset = [], [], []
    for role, name in ACCOUNTS:
        email = email_for(role)
        user = conn.execute(select(users.c.id).where(users.c.email == email)).scalar()
        if user is None:
            user = uid()
            conn.execute(users.insert().values(
                id=user, email=email, display_name=name, password_hash=security.hash_password(password),
                email_verified_at=now(), status="active", created_at=now()))
            created.append(role)
        else:
            existing.append(role)
            if reset_password:
                conn.execute(users.update().where(users.c.id == user).values(
                    password_hash=security.hash_password(password), status="active"))
                reset.append(role)
        if not conn.execute(select(memberships.c.id).where(memberships.c.org_id == org_id,
                                                           memberships.c.user_id == user)).scalar():
            conn.execute(memberships.insert().values(id=uid(), org_id=org_id, user_id=user, roles=[role],
                                                     status="active", created_at=now()))
        audit.record(conn, "demo.account_seeded", org_id=org_id, target_type="user", target_id=user,
                     details={"role": role, "created": role in created, "password_reset": role in reset})
    return {"org_id": org_id, "created_org": created_org, "created": created, "existing": existing, "reset": reset}


def seed_sample_run(conn, runtime):
    """Save the synthetic starter portfolio as an analysis everyone in the demo organisation can see (once)."""
    from . import data

    org_id = demo_org_id(conn)
    user_id = conn.execute(select(users.c.id).where(users.c.email == email_for("underwriter"))).scalar()
    if not org_id or not user_id:
        raise ModelError("not_seeded", "Seed the demo accounts first")
    principal = identity.principal_for(conn, user_id, org_id)
    label = "Nairobi starter portfolio (synthetic)"
    if any(r["label"] == label for r in data.list_runs(conn, principal)):
        return None
    rows = runtime.sample_rows()
    report = runtime.run(rows)
    data.save_run(conn, principal, report, rows, label, {}, visibility="org")
    return report["analysis_id"]


def demo_session(conn, role, request=None):
    """Start a session for a seeded demo account (one-click sign-in). Returns the raw session token."""
    if not logins_enabled():
        raise ModelError("forbidden", "One-click demo sign-in is turned off")
    if role not in ROLE_LABELS:
        raise ModelError("not_found", "Unknown demo role")
    org_id = demo_org_id(conn)
    user_id = conn.execute(select(users.c.id).where(users.c.email == email_for(role))).scalar()
    if not org_id or not user_id:
        raise ModelError("not_seeded", "Demo accounts are not set up yet: run `make seed`")
    raw, _ = identity.start_session(conn, user_id, org_id, method="demo", request=request)
    audit.record(conn, "auth.demo_login", org_id=org_id, target_type="user", target_id=user_id,
                 details={"role": role}, request=request)
    return raw
