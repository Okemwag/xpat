"""Underwriting decisions: recommendation, AI explanation and the person's final call per analysis."""

from alembic import op

revision = "0003_underwriting_decisions"
down_revision = "0002_organisation_platform"
branch_labels = None
depends_on = None


def upgrade():
    from floodcat.platform.db import decisions
    decisions.create(op.get_bind(), checkfirst=True)


def downgrade():
    from floodcat.platform.db import decisions
    decisions.drop(op.get_bind(), checkfirst=True)
