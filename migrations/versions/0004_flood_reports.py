"""Flood reports and their chunks for the drainage-deficit factor (local embeddings)."""

from alembic import op

revision = "0004_flood_reports"
down_revision = "0003_underwriting_decisions"
branch_labels = None
depends_on = None


def upgrade():
    from floodcat.platform.db import report_chunks, report_documents

    report_documents.create(op.get_bind(), checkfirst=True)
    report_chunks.create(op.get_bind(), checkfirst=True)


def downgrade():
    from floodcat.platform.db import report_chunks, report_documents

    report_chunks.drop(op.get_bind(), checkfirst=True)
    report_documents.drop(op.get_bind(), checkfirst=True)
