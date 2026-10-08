"""Organisation platform: tenancy, identity, sessions, RBAC data, audit log (append-only), business data."""

from alembic import op

revision = "0002_organisation_platform"
down_revision = "0001_initial_postgis"
branch_labels = None
depends_on = None


def upgrade():
    from floodcat.platform.db import APPEND_ONLY_SQL, metadata

    bind = op.get_bind()
    metadata.create_all(bind)
    for statement in APPEND_ONLY_SQL["postgresql"]:
        bind.exec_driver_sql(statement)


def downgrade():
    from floodcat.platform.db import metadata

    bind = op.get_bind()
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS audit_no_change ON audit_events;")
    metadata.drop_all(bind)
