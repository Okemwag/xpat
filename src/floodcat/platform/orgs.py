"""Organisation administration: settings, teams, access reviews, support access, flags, usage, lifecycle, export.

ORG-06…10, RBAC-09, ADM-01…11, ACC-01…02, DATA-05…06.
"""

import json
from datetime import timedelta
from sqlalchemy import func, select
from ..core.errors import ModelError
from . import audit
from .db import (
    feature_flags,
    memberships,
    organisations,
    runs,
    sso_configs,
    support_grants,
    team_members,
    teams,
    usage,
    users,
    now,
    uid,
)
from .identity import (
    DEFAULT_SETTINGS,
    _aware,
    _member,
    require_recent_auth,
    settings_for,
)
from .rbac import require

MFA_POLICIES = ("off", "admins", "all")
AI_MODES = ("off", "extraction", "full")
VISIBILITIES = ("private", "team", "org")
DORMANT_DAYS = 90


def get_org(conn, org_id):
    row = (
        conn.execute(select(organisations).where(organisations.c.id == org_id))
        .mappings()
        .first()
    )
    if not row:
        raise ModelError("not_found", "Organisation not found")
    return {**dict(row), "settings": {**DEFAULT_SETTINGS, **(row["settings"] or {})}}


def update_settings(conn, principal, changes, request=None):
    """Security and data settings (ADM-02, ADM-06). Validated; before/after audited."""
    security_keys = {
        "mfa_policy",
        "session_idle_minutes",
        "session_max_hours",
        "allowed_domains",
        "enforce_separation_of_duties",
    }
    require(
        principal,
        "security.manage" if security_keys & set(changes) else "settings.manage",
    )
    if security_keys & set(changes):
        require_recent_auth(conn, principal)
    current = settings_for(conn, principal.org_id)
    new = dict(current)
    for key, value in changes.items():
        if key not in DEFAULT_SETTINGS:
            raise ModelError("invalid_setting", f"Unknown setting {key}")
        if key == "mfa_policy" and value not in MFA_POLICIES:
            raise ModelError("invalid_setting", "MFA policy must be off, admins or all")
        if key == "ai_mode" and value not in AI_MODES:
            raise ModelError(
                "invalid_setting", "AI mode must be off, extraction or full"
            )
        if key == "default_visibility" and value not in VISIBILITIES:
            raise ModelError("invalid_setting", "Unknown visibility")
        if key == "session_idle_minutes" and not 5 <= int(value) <= 480:
            raise ModelError("invalid_setting", "Idle timeout must be 5–480 minutes")
        if key == "session_max_hours" and not 1 <= int(value) <= 72:
            raise ModelError("invalid_setting", "Session lifetime must be 1–72 hours")
        if key in ("retention_runs_days",) and not 30 <= int(value) <= 3650:
            raise ModelError("invalid_setting", "Retention must be 30–3650 days")
        if key == "retention_audit_days" and int(value) < 365:
            raise ModelError(
                "invalid_setting", "Audit records are kept for at least one year"
            )
        if key == "allowed_domains":
            value = sorted(
                {str(d).strip().lower().lstrip("@") for d in value if str(d).strip()}
            )
            if any("." not in d or " " in d for d in value):
                raise ModelError(
                    "invalid_setting", "Enter domains like reinsurer.co.ke"
                )
        if key in (
            "authority_limit_loss_kes",
            "authority_limit_tiv_kes",
        ) and value not in (None, ""):
            value = float(value)
            if value <= 0:
                raise ModelError("invalid_setting", "Authority limits must be positive")
        new[key] = value
    conn.execute(
        organisations.update()
        .where(organisations.c.id == principal.org_id)
        .values(settings=new)
    )
    audit.record(
        conn,
        "org.settings_changed",
        actor=principal,
        target_type="organisation",
        target_id=principal.org_id,
        details={
            "before": {k: current.get(k) for k in changes},
            "after": {k: new[k] for k in changes},
        },
        request=request,
    )
    return new


def update_profile(conn, principal, profile, request=None):
    require(principal, "settings.manage")
    allowed = {
        "legal_name",
        "country",
        "address",
        "dpo_contact",
        "technical_contact",
        "billing_contact",
    }
    clean = {k: str(v)[:300] for k, v in (profile or {}).items() if k in allowed}
    org = get_org(conn, principal.org_id)
    conn.execute(
        organisations.update()
        .where(organisations.c.id == principal.org_id)
        .values(
            profile={**(org["profile"] or {}), **clean},
            legal_name=clean.get("legal_name", org["legal_name"]),
            country=clean.get("country", org["country"]),
        )
    )
    audit.record(
        conn,
        "org.profile_changed",
        actor=principal,
        target_type="organisation",
        target_id=principal.org_id,
        details={"fields": sorted(clean)},
        request=request,
    )


# Teams (ORG-06, ADM-04) ---------------------------------------------------------------------------------
def create_team(conn, principal, name, request=None):
    require(principal, "teams.manage")
    name = str(name or "").strip()
    if not name:
        raise ModelError("invalid_team", "Team name required")
    if conn.execute(
        select(teams.c.id).where(
            teams.c.org_id == principal.org_id, teams.c.name == name
        )
    ).scalar():
        raise ModelError("exists", "A team with that name exists")
    team_id = uid()
    conn.execute(
        teams.insert().values(
            id=team_id, org_id=principal.org_id, name=name[:120], created_at=now()
        )
    )
    audit.record(
        conn,
        "team.created",
        actor=principal,
        target_type="team",
        target_id=team_id,
        details={"name": name},
        request=request,
    )
    return team_id


def _team(conn, org_id, team_id):
    row = (
        conn.execute(
            select(teams).where(teams.c.id == team_id, teams.c.org_id == org_id)
        )
        .mappings()
        .first()
    )
    if not row:
        raise ModelError("not_found", "Team not found")
    return row


def set_team_members(conn, principal, team_id, user_ids, request=None):
    require(principal, "teams.manage")
    _team(conn, principal.org_id, team_id)
    for user_id in user_ids:
        _member(conn, principal.org_id, user_id)
    before = {
        r[0]
        for r in conn.execute(
            select(team_members.c.user_id).where(team_members.c.team_id == team_id)
        )
    }
    conn.execute(team_members.delete().where(team_members.c.team_id == team_id))
    if user_ids:
        conn.execute(
            team_members.insert(),
            [{"team_id": team_id, "user_id": u} for u in dict.fromkeys(user_ids)],
        )
    audit.record(
        conn,
        "team.members_changed",
        actor=principal,
        target_type="team",
        target_id=team_id,
        details={
            "added": sorted(set(user_ids) - before),
            "removed": sorted(before - set(user_ids)),
        },
        request=request,
    )


def delete_team(conn, principal, team_id, request=None):
    require(principal, "teams.manage")
    _team(conn, principal.org_id, team_id)
    conn.execute(team_members.delete().where(team_members.c.team_id == team_id))
    conn.execute(runs.update().where(runs.c.team_id == team_id).values(team_id=None))
    conn.execute(teams.delete().where(teams.c.id == team_id))
    audit.record(
        conn,
        "team.deleted",
        actor=principal,
        target_type="team",
        target_id=team_id,
        request=request,
    )


def list_teams(conn, org_id):
    rows = (
        conn.execute(
            select(teams).where(teams.c.org_id == org_id).order_by(teams.c.name)
        )
        .mappings()
        .all()
    )
    out = []
    for t in rows:
        members = [
            r[0]
            for r in conn.execute(
                select(team_members.c.user_id).where(team_members.c.team_id == t["id"])
            )
        ]
        out.append({**dict(t), "member_ids": members})
    return out


# Access review (RBAC-09, ADM-05) ------------------------------------------------------------------------
def access_review(conn, principal):
    require(principal, "access_review.read")
    q = (
        select(
            users.c.id,
            users.c.email,
            users.c.display_name,
            users.c.last_login_at,
            users.c.mfa_enabled_at,
            memberships.c.roles,
            memberships.c.status,
            memberships.c.created_at,
        )
        .join(memberships, memberships.c.user_id == users.c.id)
        .where(memberships.c.org_id == principal.org_id)
    )
    cutoff = now() - timedelta(days=DORMANT_DAYS)
    rows = []
    for r in conn.execute(q).mappings():
        last = _aware(r["last_login_at"])
        rows.append(
            {
                **dict(r),
                "dormant": r["status"] == "active" and (last is None or last < cutoff),
                "admin_without_mfa": r["status"] == "active"
                and bool({"owner", "admin"} & set(r["roles"]))
                and r["mfa_enabled_at"] is None,
            }
        )
    audit.record(
        conn,
        "access_review.generated",
        actor=principal,
        target_type="organisation",
        target_id=principal.org_id,
    )
    return rows


# Support access (ADM-10) ------------------------------------------------------------------------------
def grant_support(conn, principal, staff_email, hours, reason, request=None):
    """Customer-approved, time-limited access for Xpat support staff; visible in the audit log."""
    require(principal, "support.grant")
    require_recent_auth(conn, principal)
    staff = (
        conn.execute(
            select(users).where(users.c.email == str(staff_email).strip().lower())
        )
        .mappings()
        .first()
    )
    if not staff or not staff["is_platform_admin"]:
        raise ModelError("not_found", "No Xpat support account with that e-mail")
    if not str(reason or "").strip():
        raise ModelError("reason_required", "Give a reason (e.g. ticket number)")
    if not 1 <= int(hours) <= 72:
        raise ModelError("invalid", "Support access lasts 1–72 hours")
    grant_id = uid()
    conn.execute(
        support_grants.insert().values(
            id=grant_id,
            org_id=principal.org_id,
            granted_by=principal.user_id,
            staff_user_id=staff["id"],
            reason=reason,
            created_at=now(),
            expires_at=now() + timedelta(hours=int(hours)),
        )
    )
    audit.record(
        conn,
        "support.granted",
        actor=principal,
        target_type="user",
        target_id=staff["id"],
        details={"hours": int(hours), "reason": reason},
        request=request,
    )
    return grant_id


def revoke_support(conn, principal, grant_id, request=None):
    require(principal, "support.grant")
    n = conn.execute(
        support_grants.update()
        .where(
            support_grants.c.id == grant_id,
            support_grants.c.org_id == principal.org_id,
            support_grants.c.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    ).rowcount
    if not n:
        raise ModelError("not_found", "Grant not found")
    audit.record(
        conn,
        "support.revoked",
        actor=principal,
        target_type="support_grant",
        target_id=grant_id,
        request=request,
    )


def active_support_grant(conn, org_id, staff_user_id):
    return conn.execute(
        select(support_grants.c.id).where(
            support_grants.c.org_id == org_id,
            support_grants.c.staff_user_id == staff_user_id,
            support_grants.c.revoked_at.is_(None),
            support_grants.c.expires_at > now(),
        )
    ).scalar()


def list_support_grants(conn, org_id):
    q = (
        select(support_grants)
        .where(support_grants.c.org_id == org_id)
        .order_by(support_grants.c.created_at.desc())
    )
    return [
        dict(r)
        | {"active": r["revoked_at"] is None and _aware(r["expires_at"]) > now()}
        for r in conn.execute(q).mappings()
    ]


# Platform administration (ADM-09, ADM-11, ORG-10) -------------------------------------------------------
def list_orgs(conn, principal):
    require(principal, "platform.manage")
    q = (
        select(
            organisations.c.id,
            organisations.c.name,
            organisations.c.status,
            organisations.c.plan,
            organisations.c.seats,
            organisations.c.created_at,
            func.count(memberships.c.id).label("members"),
        )
        .outerjoin(
            memberships,
            (memberships.c.org_id == organisations.c.id)
            & (memberships.c.status == "active"),
        )
        .group_by(organisations.c.id)
        .order_by(organisations.c.created_at.desc())
    )
    return [dict(r) for r in conn.execute(q).mappings()]


def set_org_status(conn, principal, org_id, status, request=None):
    """Suspend (read-only), reactivate, or close (export window of 30 days, then deletion by the retention job)."""
    require(principal, "platform.manage")
    require_recent_auth(conn, principal)
    if status not in ("trial", "active", "suspended", "closed"):
        raise ModelError("invalid", "Unknown status")
    values = {"status": status}
    if status == "closed":
        values.update(closed_at=now(), export_until=now() + timedelta(days=30))
    conn.execute(
        organisations.update().where(organisations.c.id == org_id).values(**values)
    )
    audit.record(
        conn,
        f"org.{status}",
        actor=principal,
        org_id=org_id,
        target_type="organisation",
        target_id=org_id,
        request=request,
    )


def set_plan(conn, principal, org_id, plan, seats, request=None):
    require(principal, "platform.manage")
    if not 1 <= int(seats) <= 10000:
        raise ModelError("invalid", "Seats must be 1–10000")
    conn.execute(
        organisations.update()
        .where(organisations.c.id == org_id)
        .values(plan=str(plan)[:40], seats=int(seats))
    )
    audit.record(
        conn,
        "org.plan_changed",
        actor=principal,
        org_id=org_id,
        target_type="organisation",
        target_id=org_id,
        details={"plan": plan, "seats": int(seats)},
        request=request,
    )


FLAGS = ("ai_extraction", "ai_evidence", "submissions", "api_access")


def set_flag(conn, principal, org_id, flag, enabled, request=None):
    require(principal, "platform.manage")
    if flag not in FLAGS:
        raise ModelError("invalid", "Unknown feature flag")
    conn.execute(
        feature_flags.delete().where(
            feature_flags.c.org_id == org_id, feature_flags.c.flag == flag
        )
    )
    conn.execute(
        feature_flags.insert().values(org_id=org_id, flag=flag, enabled=bool(enabled))
    )
    audit.record(
        conn,
        "org.flag_changed",
        actor=principal,
        org_id=org_id,
        target_type="organisation",
        target_id=org_id,
        details={"flag": flag, "enabled": bool(enabled)},
        request=request,
    )


def flag_enabled(conn, org_id, flag):
    value = conn.execute(
        select(feature_flags.c.enabled).where(
            feature_flags.c.org_id == org_id, feature_flags.c.flag == flag
        )
    ).scalar()
    return True if value is None else bool(value)


# Usage (ADM-08, ACC-03) ---------------------------------------------------------------------------------
def record_usage(conn, org_id, user_id, kind, amount=1):
    conn.execute(
        usage.insert().values(
            org_id=org_id, user_id=user_id, at=now(), kind=kind, amount=int(amount)
        )
    )


def usage_summary(conn, principal, days=30):
    require(principal, "usage.read")
    q = (
        select(usage.c.kind, func.sum(usage.c.amount))
        .where(
            usage.c.org_id == principal.org_id,
            usage.c.at >= now() - timedelta(days=days),
        )
        .group_by(usage.c.kind)
    )
    return {k: int(v) for k, v in conn.execute(q)}


# Export (DATA-05) ---------------------------------------------------------------------------------------
def export_org(conn, principal, request=None):
    """Everything the organisation owns, as one JSON document (runs without encrypted inputs)."""
    require(principal, "settings.manage")
    require_recent_auth(conn, principal)
    from .db import (
        assumption_sets,
        audit_events,
        comments,
        decisions,
        evidence,
        extractions,
        submissions,
    )

    org_id = principal.org_id

    def rows(table, exclude=()):
        return [
            {k: v for k, v in r.items() if k not in exclude}
            for r in conn.execute(
                select(table).where(table.c.org_id == org_id)
            ).mappings()
        ]

    data = {
        "organisation": {k: v for k, v in get_org(conn, org_id).items()},
        "teams": list_teams(conn, org_id),
        "members": [
            dict(r)
            for r in conn.execute(
                select(
                    users.c.id,
                    users.c.email,
                    users.c.display_name,
                    memberships.c.roles,
                    memberships.c.status,
                )
                .join(memberships, memberships.c.user_id == users.c.id)
                .where(memberships.c.org_id == org_id)
            ).mappings()
        ],
        "runs": rows(runs, ("inputs_enc",)),
        "extractions": rows(extractions),
        "evidence": rows(evidence),
        "assumption_sets": rows(assumption_sets),
        "submissions": rows(submissions),
        "decisions": rows(decisions),
        "comments": rows(comments),
        "audit_events": rows(audit_events),
        "sso": [
            {k: v for k, v in r.items() if k != "client_secret_enc"}
            for r in conn.execute(
                select(sso_configs).where(sso_configs.c.org_id == org_id)
            ).mappings()
        ],
    }
    audit.record(
        conn,
        "org.exported",
        actor=principal,
        target_type="organisation",
        target_id=org_id,
        request=request,
    )
    return json.dumps(data, default=str, indent=1)


# Quotas (SEC-05) -------------------------------------------------------------------------------------------
import os as _os

QUOTAS = {"ai_user_per_hour": 60, "ai_org_per_hour": 600, "uploads_user_per_hour": 120}


def _quota(name):
    return int(_os.getenv(f"FLOODCAT_QUOTA_{name.upper()}", QUOTAS[name]))


def check_ai_quota(conn, principal):
    """Called before every Gemini request on behalf of a user."""
    from .identity import rate_limit

    rate_limit(
        conn,
        f"ai-user:{principal.user_id}",
        _quota("ai_user_per_hour"),
        timedelta(hours=1),
        "You have reached the hourly limit for AI requests. Try again later.",
    )
    rate_limit(
        conn,
        f"ai-org:{principal.org_id}",
        _quota("ai_org_per_hour"),
        timedelta(hours=1),
        "Your organisation has reached its hourly limit for AI requests. Try again later.",
    )
    record_usage(conn, principal.org_id, principal.user_id, "ai_calls", 1)


def check_upload_quota(conn, principal):
    from .identity import rate_limit

    rate_limit(
        conn,
        f"upload-user:{principal.user_id}",
        _quota("uploads_user_per_hour"),
        timedelta(hours=1),
        "You have reached the hourly upload limit. Try again later.",
    )
