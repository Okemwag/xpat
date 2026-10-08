.PHONY: install test test-postgres demo serve outputs app migrate db eval-ingestion retention alerts
RUN = uv run --extra ui --extra ai --extra geo
ENV = set -a; [ -f .env ] && . ./.env; set +a;

install:
	uv sync --extra dev --extra geo --extra ui --extra ai
test:
	uv run --extra dev --extra geo --extra ui --extra ai python -m pytest -q
# Platform tests against a real PostgreSQL (start it with `make db`).
test-postgres:
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+psycopg://floodcat:floodcat-local-only@127.0.0.1:5433/floodcat_test} \
	uv run --extra dev --extra geo python -m pytest -q tests/test_platform.py -k "not tampering"
demo:
	uv run --extra geo flood-cat analyse data/exposure_nairobi_with_hazard.csv --rasters data --hotspots data/nairobi_hotspots_geocoded.csv --output runtime/baseline-report.json
outputs:
	uv run --extra geo python scripts/build_day1_outputs.py
eval-ingestion:
	uv run --extra ai --extra geo python scripts/evaluate_ingestion.py
db:
	docker compose up -d db
# Create or upgrade the platform tables (PostgreSQL via FLOODCAT_DATABASE_URL; SQLite needs no migration).
migrate:
	@$(ENV) if [ -n "$$FLOODCAT_DATABASE_URL" ]; then uv run alembic upgrade head; else uv run flood-cat init-db; fi
# The sign-in/API server (port 8000) and the interface (port 8501) together; Ctrl+C stops both.
app: migrate
	@$(ENV) trap 'kill 0' INT TERM EXIT; \
	$(RUN) uvicorn floodcat.api.app:create_app --factory --host 127.0.0.1 --port 8000 & \
	$(RUN) streamlit run app/streamlit_app.py --server.headless true --server.port 8501
serve:
	@$(ENV) $(RUN) uvicorn floodcat.api.app:create_app --factory --host 127.0.0.1 --port 8000
retention:
	@$(ENV) uv run flood-cat retention
alerts:
	@$(ENV) uv run flood-cat alerts
