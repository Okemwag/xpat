.PHONY: install test test-postgres demo serve outputs app migrate db eval-ingestion imd-index eval-imd places eval-drainage retention alerts seed report
RUN = uv run --extra ui --extra ai --extra geo --extra embed
ENV = set -a; [ -f .env ] && . ./.env; set +a;

install:
	uv sync --extra dev --extra geo --extra ui --extra ai --extra embed
test:
	uv run --extra dev --extra geo --extra ui --extra ai python -m pytest -q
# Platform tests against a real PostgreSQL (start it with `make db`).
test-postgres:
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+psycopg://floodcat:floodcat-local-only@127.0.0.1:5433/floodcat_test} \
	uv run --extra dev --extra geo python -m pytest -q tests/test_platform.py tests/test_drainage.py -k "not tampering"
demo:
	uv run --extra geo flood-cat analyse data/exposure_nairobi_with_hazard.csv --rasters data --hotspots data/nairobi_hotspots_geocoded.csv --output runtime/baseline-report.json
outputs:
	uv run --extra geo python scripts/build_day1_outputs.py
imd-index:
	uv run --extra geo --extra osm python scripts/build_imd_index.py
eval-imd:
	uv run --extra geo python scripts/evaluate_imd.py
places:
	uv run --extra geo --extra osm python scripts/build_places.py
eval-drainage:
	uv run --extra embed python scripts/evaluate_drainage.py
eval-ingestion:
	uv run --extra ai --extra geo python scripts/evaluate_ingestion.py
db:
	docker compose up -d db
# Create or upgrade the platform tables (PostgreSQL via FLOODCAT_DATABASE_URL; SQLite needs no migration).
migrate:
	@$(ENV) if [ -n "$$FLOODCAT_DATABASE_URL" ]; then uv run alembic upgrade head; else uv run flood-cat init-db; fi
# The sign-in/API server (port 8000) and the interface (port 8501) together; Ctrl+C stops both.
app: migrate
	@$(ENV) $(RUN) python scripts/run_app.py
serve:
	@$(ENV) $(RUN) uvicorn floodcat.api.app:create_app --factory --host 127.0.0.1 --port 8000
# Demo organisation with one account per role (refuses when FLOODCAT_ENV=production). Pass ARGS="--reset-password".
# Submission note and explainer PDFs, built from the model (ai-effect demo refreshed without a new AI call; add LIVE=1 for one)
report:
	@$(ENV) uv run --extra geo --extra ai --extra embed python scripts/demo_ai_effect.py $(if $(LIVE),,--skip-llm)
	uv run --extra geo --with reportlab --with matplotlib --with pillow python scripts/build_vulnerability_explainer.py
	uv run --extra geo --with reportlab --with matplotlib --with pillow python scripts/build_submission_report.py
seed: migrate
	@$(ENV) uv run --extra geo flood-cat seed-demo $(ARGS)
retention:
	@$(ENV) uv run flood-cat retention
alerts:
	@$(ENV) uv run flood-cat alerts
