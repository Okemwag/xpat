# Validation record

Current checked results for the supplied Nairobi files:

- After adding the explicit severity interpretation and tier audit, the local test run without a database URL reported **29 passed, 5 skipped**. The skipped cases require a PostGIS test database.
- `uv run --locked --extra dev --extra geo --extra ml python -m pytest -q` with `TEST_DATABASE_URL` pointed at a separate migrated PostGIS database: **34 passed**. One upstream Starlette/httpx deprecation warning remains.
- `PYTHONPATH=src python -m floodcat.cli analyse data/exposure_nairobi_with_hazard.csv --output runtime/baseline-report.json`: **600 properties modelled**, supplied TIV **KES 63,635,075,000.00**.
- All five portfolio scenario totals reconcile exactly with their property losses. Current illustrative common-tier gross damage proxy: **KES 1,793,116,247.37**.
- `PYTHONPATH=src python -m floodcat.cli sensitivity data/exposure_nairobi_with_hazard.csv --output runtime/sensitivity.json`: completed. With area-times-cost values, the common-tier loss is **KES 179,311,474.93**. This is an alternative input assumption, not a corrected portfolio.
- `python -m compileall -q src tests migrations`, `docker compose config --quiet`, and `git diff --check`: passed.
- `uv run --locked --extra geo flood-cat audit-data data --output docs/DATA_AUDIT.json`: passed. All **600** prepared-score rows matched the corresponding GeoTIFF samples within `1e-7`; all exposure and hotspot points were covered; the common raster scored **12 of 24** supplied hotspots above zero. The audit records SHA-256 hashes for all eight files.
- Raster analysis of `data/exposure_nairobi_synthetic.csv` against the five GeoTIFFs matched the prepared-file analysis at every property score and every scenario portfolio loss.
- PostGIS 16 / PostgreSQL 16 container started and reported healthy on local port 5433. Alembic revision `0001_initial_postgis` applied to both development and separate test databases.
- `flood-cat import-data` loaded **600 prepared exposure rows** with their five scores and **24 hotspots** into the development database. The integration suite verified idempotent import and an indexed spatial-distance query against the test database.

The backend Docker build reached the `uv sync` dependency-download step but was stopped before completion because the container registry/package transfer was slow. The Compose configuration and PostGIS database service were verified; the backend image itself remains unverified. The previous validation claims from the archive applied to a different environment and demo fixtures; they are not treated as current results.

The baseline is an uncalibrated demonstration on synthetic exposure and proxy hazard. These checks verify program behaviour and internal arithmetic, not real flood predictive skill or insured loss accuracy.
