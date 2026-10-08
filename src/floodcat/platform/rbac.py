"""Roles and permissions as code (RBAC-01…05). One `can()` used by the interface and the API."""

from dataclasses import dataclass, field
from ..core.errors import ModelError

ROLES = {
    "owner": "Organisation owner — everything an admin can do, plus plan, billing and closing the organisation",
    "admin": "Organisation admin — users, invitations, roles, teams, SSO and security policy, audit log",
    "head_uw": "Head of underwriting / model owner — approves house assumptions, evidence and referrals; sets underwriting rules",
    "underwriter": "Underwriter — upload schedules and documents, run analyses, export",
    "analyst": "Analyst / cat modeller — as underwriter, plus assumption sandboxes and proposals",
    "reviewer": "Evidence reviewer — approves or withdraws AI-extracted flood evidence",
    "viewer": "Viewer — reads results shared with them",
    "auditor": "Auditor / compliance — reads the audit log and run records, no business actions",
}
ASSIGNABLE = tuple(ROLES)

_ADMIN = {
    "users.manage",
    "security.manage",
    "audit.read",
    "teams.manage",
    "settings.manage",
    "tokens.manage",
    "usage.read",
    "access_review.read",
}
_WORK = {
    "runs.create",
    "runs.read",
    "runs.export",
    "ai.extract",
    "evidence.add",
    "submissions.manage",
    "comments.write",
    "underwriting.decide",
}
PERMISSIONS = {
    "owner": _ADMIN | {"org.billing", "org.close", "runs.read", "support.grant"},
    "admin": _ADMIN | {"support.grant"},
    "head_uw": _WORK
    | {
        "assumptions.propose",
        "assumptions.approve",
        "assumptions.sandbox",
        "evidence.approve",
        "referrals.approve",
        "underwriting.rules",
        "runs.delete_any",
        "usage.read",
    },
    "underwriter": set(_WORK),
    "analyst": _WORK
    | {"assumptions.propose", "assumptions.sandbox", "sensitivity.run"},
    "reviewer": {"runs.read", "evidence.add", "evidence.approve", "comments.write"},
    "viewer": {"runs.read", "runs.export"},
    "auditor": {"audit.read", "runs.read"},
}
ALL_PERMISSIONS = sorted(set().union(*PERMISSIONS.values()) | {"platform.manage"})


@dataclass(frozen=True)
class Principal:
    """Who is acting, in which organisation, with which roles and teams."""

    user_id: str
    email: str
    display_name: str
    org_id: str | None
    roles: tuple = ()
    team_ids: tuple = ()
    is_platform_admin: bool = False
    session_id: str | None = None
    support_access: bool = False
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def permissions(self):
        perms = (
            set().union(*(PERMISSIONS.get(r, set()) for r in self.roles))
            if self.roles
            else set()
        )
        if self.is_platform_admin:
            perms |= {"platform.manage"}
        if self.support_access:
            perms |= {"runs.read", "audit.read"}
        return perms

    def can(self, permission):
        return permission in self.permissions


def require(principal, permission):
    if principal is None or not principal.can(permission):
        raise ModelError(
            "forbidden", f"You do not have permission for this action ({permission})"
        )


def validate_roles(roles):
    roles = list(dict.fromkeys(roles or []))
    if not roles:
        raise ModelError("invalid_role", "Choose at least one role")
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        raise ModelError("invalid_role", "Unknown role: " + ", ".join(unknown))
    return roles


def can_see_run(principal, run):
    """Visibility (RBAC-06): private → owner only; team → owner's team members; org → everyone with runs.read."""
    if not principal.can("runs.read") or run["org_id"] != principal.org_id:
        return False
    if (
        run["owner_id"] == principal.user_id
        or principal.can("runs.delete_any")
        or principal.support_access
        or "auditor" in principal.roles
    ):
        return True
    if run["visibility"] == "org":
        return True
    if run["visibility"] == "team":
        return run.get("team_id") is not None and run["team_id"] in principal.team_ids
    return False
