.PHONY: install test demo serve
install:
	uv sync --extra dev --extra geo
test:
	uv run --extra dev --extra geo python -m pytest -q
demo:
	uv run --extra geo flood-cat analyse data/exposure_nairobi_with_hazard.csv --output runtime/baseline-report.json
serve:
	uv run flood-cat serve
