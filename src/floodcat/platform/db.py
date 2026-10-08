"""Schema and engine for the organisation platform (DATA-01)."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)

metadata = MetaData()


def uid():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc)


def _id():
    return Column("id", String(32), primary_key=True, default=uid)


def _org(nullable=False):
    return Column(
        "org_id",
        String(32),
        ForeignKey("organisations.id"),
        nullable=nullable,
        index=True,
    )


def _ts(name, nullable=True):
    return Column(name, DateTime(timezone=True), nullable=nullable)


organisations = Table(
    "organisations",
    metadata,
    _id(),
    Column("name", String(200), nullable=False),
    Column("legal_name", String(300)),
    Column("country", String(80)),
    Column(
        "status", String(20), nullable=False, default="trial"
    ),  # trial | active | suspended | closed
    Column("plan", String(40), nullable=False, default="pilot"),
    Column("seats", Integer, nullable=False, default=10),
    _ts("trial_ends_at"),
    _ts("created_at", False),
    _ts("closed_at"),
    _ts("export_until"),
    Column("settings", JSON, nullable=False, default=dict),
    Column("profile", JSON, nullable=False, default=dict),
)

users = Table(
    "users",
    metadata,
    _id(),
    Column("email", String(320), nullable=False, unique=True),
    Column("display_name", String(120), nullable=False),
    Column("password_hash", Text),
    _ts("email_verified_at"),
    Column(
        "status", String(20), nullable=False, default="active"
    ),  # active | deactivated | anonymised
    Column("mfa_secret_enc", Text),
    _ts("mfa_enabled_at"),
    _ts("created_at", False),
    _ts("last_login_at"),
    Column("is_platform_admin", Boolean, nullable=False, default=False),
    Column("sso_subject", String(300)),
)

memberships = Table(
    "memberships",
    metadata,
    _id(),
    _org(),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False, index=True),
    Column("roles", JSON, nullable=False, default=list),
    Column("status", String(20), nullable=False, default="active"),
    _ts("created_at", False),
    _ts("deactivated_at"),
    UniqueConstraint("org_id", "user_id"),
)

teams = Table(
    "teams",
    metadata,
    _id(),
    _org(),
    Column("name", String(120), nullable=False),
    _ts("created_at", False),
    UniqueConstraint("org_id", "name"),
)
team_members = Table(
    "team_members",
    metadata,
    Column("team_id", String(32), ForeignKey("teams.id"), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id"), primary_key=True),
)

invitations = Table(
    "invitations",
    metadata,
    _id(),
    _org(),
    Column("email", String(320), nullable=False),
    Column("roles", JSON, nullable=False),
    Column("team_ids", JSON, nullable=False, default=list),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("invited_by", String(32)),
    _ts("created_at", False),
    _ts("expires_at", False),
    _ts("accepted_at"),
    _ts("revoked_at"),
)

one_time_tokens = Table(
    "one_time_tokens",
    metadata,
    _id(),
    Column(
        "kind", String(30), nullable=False
    ),  # password_reset | email_verify | email_change
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("data", JSON, nullable=False, default=dict),
    _ts("created_at", False),
    _ts("expires_at", False),
    _ts("used_at"),
)

sessions = Table(
    "sessions",
    metadata,
    _id(),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False, index=True),
    _org(nullable=True),
    _ts("created_at", False),
    _ts("last_seen_at", False),
    _ts("expires_at", False),
    _ts("revoked_at"),
    _ts("reauth_at"),
    Column("mfa_passed", Boolean, nullable=False, default=False),
    Column("method", String(20), nullable=False, default="password"),
    Column("ip", String(64)),
    Column("user_agent", String(300)),
)

login_attempts = Table(
    "login_attempts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(400), nullable=False, index=True),
    _ts("at", False),
    Column("success", Boolean, nullable=False),
)

recovery_codes = Table(
    "recovery_codes",
    metadata,
    _id(),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False, index=True),
    Column("code_hash", String(64), nullable=False),
    _ts("used_at"),
)

api_tokens = Table(
    "api_tokens",
    metadata,
    _id(),
    _org(),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("prefix", String(16), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("scopes", JSON, nullable=False),
    _ts("created_at", False),
    _ts("expires_at", False),
    _ts("revoked_at"),
    _ts("last_used_at"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("id", String(32), nullable=False, unique=True, default=uid),
    _ts("at", False),
    _org(nullable=True),
    Column("actor_id", String(32)),
    Column("actor_roles", JSON),
    Column("action", String(80), nullable=False, index=True),
    Column("target_type", String(40)),
    Column("target_id", String(64)),
    Column("outcome", String(20), nullable=False),
    Column("ip", String(64)),
    Column("user_agent", String(300)),
    Column("request_id", String(64)),
    Column("details", JSON, nullable=False, default=dict),
    Column("prev_hash", String(64)),
    Column("hash", String(64), nullable=False),
)

sso_configs = Table(
    "sso_configs",
    metadata,
    Column("org_id", String(32), ForeignKey("organisations.id"), primary_key=True),
    Column("discovery_url", Text, nullable=False),
    Column("client_id", String(300), nullable=False),
    Column("client_secret_enc", Text, nullable=False),
    Column("default_role", String(40), nullable=False, default="viewer"),
    Column("role_mapping", JSON, nullable=False, default=dict),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("enforced", Boolean, nullable=False, default=False),
    _ts("updated_at", False),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(64), primary_key=True, default=uid),
    _org(),
    Column("owner_id", String(32), ForeignKey("users.id"), nullable=False),
    Column("team_id", String(32), ForeignKey("teams.id")),
    Column("visibility", String(10), nullable=False, default="team"),
    Column("label", String(200), nullable=False),
    _ts("created_at", False),
    _ts("deleted_at"),
    Column("submission_id", String(32)),
    Column("summary", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("inputs_enc", Text),
    Column("settings", JSON, nullable=False, default=dict),
    Column("assumption_set_id", String(32)),
)
Index("ix_runs_org_created", runs.c.org_id, runs.c.created_at)

extractions = Table(
    "extractions",
    metadata,
    _id(),
    _org(),
    Column("user_id", String(32), nullable=False),
    _ts("created_at", False),
    Column("file_sha256", String(64), nullable=False),
    Column("file_kind", String(10)),
    Column("pages", Integer),
    Column("model", String(80)),
    Column("prompt_version", String(40)),
    Column("redaction", JSON, nullable=False, default=dict),
    Column("consent", Boolean, nullable=False),
    Column("result", JSON, nullable=False),
    Column("decisions", JSON, nullable=False, default=dict),
    Column("run_id", String(64)),
    _ts("deleted_at"),
)

evidence = Table(
    "evidence_items",
    metadata,
    Column("pk", String(32), primary_key=True, default=uid),
    _org(),
    Column("evidence_id", String(100), nullable=False),
    Column("created_by", String(32)),
    Column("payload", JSON, nullable=False),
    _ts("created_at", False),
    _ts("updated_at", False),
    UniqueConstraint("org_id", "evidence_id"),
)

assumption_sets = Table(
    "assumption_sets",
    metadata,
    _id(),
    _org(),
    Column("version", Integer, nullable=False),
    Column("name", String(200), nullable=False),
    Column(
        "status", String(20), nullable=False
    ),  # draft|proposed|approved|rejected|retired
    Column("config", JSON, nullable=False),
    Column("reason", Text),
    Column("proposed_by", String(32)),
    _ts("proposed_at"),
    Column("decided_by", String(32)),
    _ts("decided_at"),
    Column("decision_note", Text),
    Column("is_default", Boolean, nullable=False, default=False),
    Column("owner_id", String(32)),
    Column("personal", Boolean, nullable=False, default=False),
    UniqueConstraint("org_id", "version"),
)

submissions = Table(
    "submissions",
    metadata,
    _id(),
    _org(),
    Column("name", String(200), nullable=False),
    Column("cedant", String(200)),
    Column("broker", String(200)),
    Column("inception", String(20)),
    Column("status", String(20), nullable=False, default="received"),
    Column("assignee_id", String(32)),
    Column("team_id", String(32)),
    Column("created_by", String(32), nullable=False),
    _ts("created_at", False),
    _ts("updated_at", False),
    Column("tiv_kes", String(40)),
    Column("loss_250_kes", String(40)),
    Column("referral_reason", Text),
)

# Underwriting decisions: the rules' recommendation (recomputed server-side), the optional AI explanation, and the person's call.
decisions = Table(
    "decisions",
    metadata,
    _id(),
    _org(),
    Column("run_id", String(64), nullable=False, index=True),
    Column("submission_id", String(32), index=True),
    Column("decided_by", String(32), nullable=False),
    _ts("created_at", False),
    Column("premium_100_kes", String(40), nullable=False),
    Column("offered_share_pct", String(20), nullable=False),
    Column("recommendation", JSON, nullable=False),
    Column("rationale", JSON),
    Column("outcome", String(10), nullable=False),
    Column("share_pct", String(20), nullable=False),
    Column("overrode", Boolean, nullable=False),
    Column("reason", Text),
)

comments = Table(
    "comments",
    metadata,
    _id(),
    _org(),
    Column("target_type", String(30), nullable=False),
    Column("target_id", String(64), nullable=False, index=True),
    Column("author_id", String(32), nullable=False),
    Column("body", Text, nullable=False),
    _ts("created_at", False),
)

notifications = Table(
    "notifications",
    metadata,
    _id(),
    _org(),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False, index=True),
    Column("kind", String(40), nullable=False),
    Column("message", Text, nullable=False),
    Column("link", String(300)),
    _ts("created_at", False),
    _ts("read_at"),
)

support_grants = Table(
    "support_grants",
    metadata,
    _id(),
    _org(),
    Column("granted_by", String(32), nullable=False),
    Column("staff_user_id", String(32), nullable=False),
    Column("reason", Text, nullable=False),
    _ts("created_at", False),
    _ts("expires_at", False),
    _ts("revoked_at"),
)

feature_flags = Table(
    "feature_flags",
    metadata,
    Column("org_id", String(32), ForeignKey("organisations.id"), primary_key=True),
    Column("flag", String(60), primary_key=True),
    Column("enabled", Boolean, nullable=False),
)

usage = Table(
    "usage",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    _org(),
    Column("user_id", String(32)),
    _ts("at", False),
    Column("kind", String(40), nullable=False),
    Column("amount", Integer, nullable=False),
)

outbox = Table(
    "email_outbox",
    metadata,
    _id(),
    Column("to", String(320), nullable=False),
    Column("subject", String(300), nullable=False),
    Column("text", Text, nullable=False),
    Column("html", Text),
    Column("kind", String(40)),
    _ts("created_at", False),
    _ts("sent_at"),
    Column("provider_id", String(120)),
    Column("error", Text),
)

geocode_cache = Table(
    "geocode_cache",
    metadata,
    _org(nullable=True),
    Column("key", String(300), nullable=False),
    Column("result", JSON, nullable=False),
    _ts("created_at", False),
    UniqueConstraint("org_id", "key"),
)

APPEND_ONLY_SQL = {
    "sqlite": [
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;",
        "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;",
    ],
    "postgresql": [
        """CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
                      BEGIN RAISE EXCEPTION 'audit log is append-only'; END; $$ LANGUAGE plpgsql;""",
        "DROP TRIGGER IF EXISTS audit_no_change ON audit_events;",
        "CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_append_only();",
    ],
}


def default_url():
    url = os.getenv("FLOODCAT_DATABASE_URL")
    if url:
        return url
    root = Path(
        os.getenv("FLOODCAT_STORE_DIR")
        or Path(__file__).resolve().parents[3] / "runtime" / "store"
    )
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{root / 'platform.db'}"


def make_engine(url=None):
    url = url or default_url()
    engine = create_engine(url, pool_pre_ping=True, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def create_schema(engine):
    """Create tables (development/tests). Production PostgreSQL uses the Alembic migration, which calls this too."""
    metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in APPEND_ONLY_SQL.get(engine.dialect.name, []):
            conn.exec_driver_sql(statement)
