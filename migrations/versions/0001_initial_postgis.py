"""Initial portfolio, hotspot, evidence, and immutable analysis schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_postgis"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
        CREATE TABLE portfolios (
            id text PRIMARY KEY,
            source_name text NOT NULL,
            source_sha256 char(64) NOT NULL UNIQUE,
            synthetic boolean NOT NULL,
            asset_count integer NOT NULL CHECK (asset_count > 0),
            tiv_kes numeric(24, 2) NOT NULL CHECK (tiv_kes >= 0),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE assets (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            portfolio_id text NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            loc_id text NOT NULL,
            location geometry(Point, 4326) NOT NULL,
            housing_class text NOT NULL,
            floor_area_m2 numeric(16, 2),
            cost_per_m2_kes numeric(18, 2),
            tiv_kes numeric(24, 2) NOT NULL CHECK (tiv_kes >= 0),
            hazard_scores jsonb NOT NULL,
            source text NOT NULL,
            synthetic boolean NOT NULL,
            UNIQUE (portfolio_id, loc_id)
        )
    """)
    op.execute("CREATE INDEX ix_assets_location ON assets USING GIST (location)")
    op.execute("CREATE INDEX ix_assets_portfolio ON assets (portfolio_id)")
    op.execute("""
        CREATE TABLE hotspots (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name text NOT NULL UNIQUE,
            location geometry(Point, 4326) NOT NULL,
            source_name text NOT NULL,
            coordinate_precision text NOT NULL,
            review_status text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_hotspots_location ON hotspots USING GIST (location)")
    op.execute("""
        CREATE TABLE evidence (
            id text PRIMARY KEY,
            payload jsonb NOT NULL,
            approved boolean NOT NULL DEFAULT false,
            location geometry(Point, 4326),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_evidence_location ON evidence USING GIST (location)")
    op.execute("CREATE INDEX ix_evidence_approved ON evidence (approved)")
    op.execute("""
        CREATE TABLE analysis_runs (
            id text PRIMARY KEY,
            portfolio_id text REFERENCES portfolios(id),
            created_at timestamptz NOT NULL,
            input_fingerprint char(64) NOT NULL,
            config_fingerprint char(64) NOT NULL,
            evidence_snapshot jsonb NOT NULL,
            payload jsonb NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_analysis_runs_created_at ON analysis_runs (created_at DESC)")


def downgrade():
    op.execute("DROP TABLE analysis_runs")
    op.execute("DROP TABLE evidence")
    op.execute("DROP TABLE hotspots")
    op.execute("DROP TABLE assets")
    op.execute("DROP TABLE portfolios")
