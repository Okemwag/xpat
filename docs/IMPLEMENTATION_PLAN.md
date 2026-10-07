# Implementation plan and boundaries

The ordered implementation tasks are in [IMPLEMENTATION_BACKLOG.md](IMPLEMENTATION_BACKLOG.md). Tasks 1–19 establish the baseline and spatial persistence. Tasks 20–45 cover the LLM evidence path, independent validation, and underwriter presentation. Tasks 46–53 describe the later product phase.

## Current modelling path

The supplied 600-property portfolio and five GeoTIFFs support a reproducible baseline run. `audit-data` verifies dataset hashes, row counts, raster metadata, prepared score sampling, and hotspot detection. `analyse` calculates gross damage proxies from the supplied susceptibility scores. `sensitivity` varies unresolved TIV and model assumptions without treating the range as a confidence interval.

The score-to-damage curves remain illustrative. The raster scores are **not** flood depths, and the assigned return periods are **not** estimated Nairobi event frequencies. No AAL, insured-policy loss, or net reinsurance loss is claimed. The supplied TIV differs by approximately 10× from area times cost; the source of the discrepancy has not been resolved.

## Storage and extension boundary

PostgreSQL/PostGIS is the primary persistence layer. Alembic migrations create indexed point geometries for imported assets, hotspot references, and evidence, plus JSONB snapshots for analyses. GeoTIFFs remain files and are sampled with Rasterio. The hazard-provider boundary and financial calculations remain independent of the database and API.

The optional logistic classifier is an experiment with synthetic fixture labels, not a validated Nairobi hazard enhancement. A future LLM workflow must extract sourced evidence, preserve review status and location ambiguity, then apply a documented adjustment to hazard. Evaluation hotspot locations and their evidence must not be reused as enhancement inputs. Improvements must be shown on independent held-out observations, and increased loss alone is not evidence of improved accuracy.

## Product boundaries

The hackathon result is a prototype for synthetic exposure and gross damage scenarios. A commercial pilot requires licensed data, validated hazard and vulnerability models, tenant isolation, policy terms, audit controls, and observed-outcome testing. The platform should make uncertainty and out-of-coverage assets explicit.
