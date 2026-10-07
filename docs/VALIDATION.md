# Validation record

Current checked results for the supplied Nairobi files:

- `PYTHONPATH=src python -m pytest -q tests/test_pipeline.py tests/test_ml.py`: **26 passed** using the relocated test fixtures.
- `PYTHONPATH=src python -m floodcat.cli analyse data/exposure_nairobi_with_hazard.csv --output runtime/baseline-report.json`: **600 properties modelled**, supplied TIV **KES 63,635,075,000.00**.
- All five portfolio scenario totals reconcile exactly with their property losses. Current illustrative common-tier gross damage proxy: **KES 1,793,116,247.37**.
- `PYTHONPATH=src python -m floodcat.cli sensitivity data/exposure_nairobi_with_hazard.csv --output runtime/sensitivity.json`: completed. With area-times-cost values, the common-tier loss is **KES 179,311,474.93**. This is an alternative input assumption, not a corrected portfolio.
- `python -m compileall -q src tests migrations`, `docker compose config --quiet`, and `git diff --check`: passed.
- PostGIS 16 / PostgreSQL 16 container started and reported healthy on local port 5433. A separate `floodcat_test` database was created.

Pending at this checkpoint: `uv sync` dependency installation, full suite including raster/API tests, Alembic upgrade, starter-data import, and end-to-end PostGIS verification. The previous validation claims from the archive applied to a different environment and demo fixtures; they are not treated as current results.

The baseline is an uncalibrated demonstration on synthetic exposure and proxy hazard. These checks verify program behaviour and internal arithmetic, not real flood predictive skill or insured loss accuracy.
