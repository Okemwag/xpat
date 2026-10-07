.PHONY: install test demo serve outputs app eval-ingestion
install:
	uv sync --extra dev --extra geo --extra ui --extra ai
test:
	uv run --extra dev --extra geo python -m pytest -q
demo:
	uv run --extra geo flood-cat analyse data/exposure_nairobi_with_hazard.csv --rasters data --hotspots data/nairobi_hotspots_geocoded.csv --output runtime/baseline-report.json
serve:
	uv run flood-cat serve
outputs:
	uv run --extra geo python scripts/build_day1_outputs.py
app:
	uv run --extra ui --extra ai streamlit run app/streamlit_app.py
eval-ingestion:
	uv run --extra ai --extra geo python scripts/evaluate_ingestion.py
