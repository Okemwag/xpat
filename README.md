# Nairobi Flood CAT Backend

An assumption-transparent CAT risk prototype for Team A. It accepts a synthetic Nairobi property portfolio, attaches supplied flood-susceptibility proxy scores, applies illustrative construction vulnerability curves, and calculates gross damage losses, accumulation, and assumed scenario EP points. It is **not a calibrated underwriting model**.

The eight supplied files are in `data/`. The 600 locations are synthetic; the five GeoTIFFs are susceptibility proxies derived from terrain and mapped streams, not observed flood depths. The 24 hotspot coordinates are approximate neighbourhood reference points, not verified flooded buildings.

## Set up with uv

`uv` manages the Python environment and locked dependencies. Python 3.11+ is required.

```bash
uv sync --locked --extra dev --extra geo --extra ml
uv run --locked --extra dev --extra geo --extra ml python -m pytest -q
```

The logistic classifier remains an optional experiment. For baseline analysis, `--extra ml` is unnecessary. API integration tests require a migrated PostGIS database and `TEST_DATABASE_URL`; they skip when it is absent.

## Database

Start the local PostGIS service and apply the versioned migration:

```bash
docker compose up -d db
export FLOODCAT_DATABASE_URL='postgresql+psycopg://floodcat:floodcat-local-only@127.0.0.1:5433/floodcat'
uv run --locked alembic upgrade head
uv run --locked flood-cat import-data
```

For another local database password, set `FLOODCAT_DB_PASSWORD` in `.env` for Compose and use the matching value in `FLOODCAT_DATABASE_URL`. The default credential is for local development only. `import-data` inserts the supplied 600 synthetic assets from `data/exposure_nairobi_with_hazard.csv`, including all five attached scores, and 24 named hotspots into spatial tables. The baseline CLI can also analyse CSV files directly without a database. The API requires PostGIS because analysis snapshots and reviewed evidence are stored there.

The Compose stack also has a `migrate` service and a `backend` service. `docker compose up --build backend` starts the database, runs migrations, then starts the API on `127.0.0.1:8000`; API documentation is at `/docs`.

## Inspect and analyse the supplied files

```bash
uv run --locked --extra geo flood-cat audit-data data --output docs/DATA_AUDIT.json
uv run --locked --extra geo flood-cat analyse data/exposure_nairobi_with_hazard.csv --output runtime/baseline-report.json
uv run --locked --extra geo flood-cat analyse data/exposure_nairobi_synthetic.csv --rasters data --output runtime/raster-report.json
uv run --locked --extra geo flood-cat sensitivity data/exposure_nairobi_with_hazard.csv --output runtime/sensitivity.json
uv run --locked flood-cat serve
```

The two analysis commands should calculate the same property scores and losses. The audit records file hashes, row counts, raster metadata, prepared-versus-sampled differences, and hotspot detection. The sensitivity output compares supplied TIV with `floor_area_m2 × cost_per_m2_kes`, vulnerability curve scales, and an alternate return-period mapping. These are **assumption scenarios**, not confidence intervals.

## Known data and model limitations

The supplied CSV sums to **KES 63,635,075,000 TIV**. `Dataset_Metadata.docx` states **KES 6,363,470,000**. The CSV TIV is approximately 10 times `floor_area_m2 × cost_per_m2_kes`. The reason is unresolved. The program retains the supplied TIV and flags mismatches; it does not silently correct values. See [data reconciliation](docs/DATA_RECONCILIATION.md).

The default vulnerability functions map a 0–1 **susceptibility score** to a damage ratio. Their parameters are illustrative and have not been digitized from JRC depth-damage curves. No physical flood depth is inferred by the default model. The five tier return periods (10, 25, 50, 100, 250 years, from narrowest to widest raster) are assumptions, not fitted Nairobi event frequencies. The EP output is therefore a set of assumed scenario points, not a calibrated annual loss distribution or AAL. The baseline common-tier raster identifies 12 of the 24 supplied positive hotspot points at a score above zero; this is not a predictive accuracy figure.

Losses are **gross damage proxies** (`TIV × damage ratio`). No policy deductibles, limits, treaty terms, or net reinsurance loss are implemented. Missing and out-of-coverage hazard values are never changed into zero scores. Invalid records block analysis unless the caller explicitly requests a partial run.

## API and architecture

The FastAPI contract covers model metadata, analysis of JSON or CSV rows, persisted result retrieval and export, and evidence extraction/review. Use `X-API-Key` when `FLOODCAT_API_TOKEN` is set. The prototype shared token is not tenant-level security. The optional classifier only demonstrates training/inference plumbing; it has no validated Nairobi accuracy. LLM-based flood-evidence adjustment remains a planned task in [the backlog](docs/IMPLEMENTATION_BACKLOG.md).

Core calculations stay in `hazard/`, `vulnerability/`, and `financial/`. `services/analysis.py` orchestrates runs. `storage/repository.py` stores inputs, approved evidence, and complete result snapshots in PostGIS. GeoTIFFs remain files and are sampled by Rasterio; PostGIS stores exposure, hotspot, and evidence geometries. Model and evidence provenance accompany outputs.

See [the backlog](docs/IMPLEMENTATION_BACKLOG.md), [implementation plan](docs/IMPLEMENTATION_PLAN.md), and [validation record](docs/VALIDATION.md) for progress and remaining work.
