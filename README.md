# Nairobi Flood CAT Backend

A runnable Python backend scaffold for Team A. No frontend is included. The default path works offline: prepared synthetic exposure → validation → attached hazard → construction vulnerability → gross damage loss → accumulation → assumed scenario EP points → persisted/exportable results.

**This is an uncalibrated prototype, not an underwriting-ready model.** The three attachments were documentation only, so the actual 600-property CSV and five GeoTIFFs must still be added. The supplied four-property demo and training fixture are invented examples, not the starter portfolio.

## Start

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev,ml,geo]'
python -m pytest -q
python -m floodcat.cli analyse data/demo/exposure.csv --output runtime/demo-report.json
python -m floodcat.cli serve
```

API documentation: http://127.0.0.1:8000/docs. Local service binds to loopback. Environment variables can be exported in your shell; `.env` is a template, not automatically loaded. Docker Compose can read `.env` for its token substitution.

## Actual starter data

Put CSVs and GeoTIFFs in `data/raw/`. CSV fields:

`loc_id, lat, lon, housing_class, floor_area_m2, cost_per_m2_kes, tiv_kes, synthetic, source`

The prepared route additionally requires `hazard_score_extreme`, `hazard_score_severe`, `hazard_score_moderate`, `hazard_score_occasional`, `hazard_score_common`.

```bash
python -m floodcat.cli analyse data/raw/exposure_nairobi_with_hazard.csv
python -m floodcat.cli analyse data/raw/exposure_nairobi_synthetic.csv --rasters data/raw
```

Errors fail the analysis by default. `--allow-partial` explicitly excludes unusable records and reports counts, accepted TIV, modelled TIV and unmodelled accepted TIV. Unknown locations, no-data and absent scores do not become zero risk. Same-coordinate properties are warned about, not automatically removed; duplicate IDs are excluded. TIV discrepancies are flagged while the provided value is retained.

## Important corrections from the attachments

`Dataset_Metadata.docx` lists **KES 6,363,470,000** total TIV for the 600-property Nairobi starter portfolio. The previous KES 63.6B and ×10 multiplier are not supported by this metadata and are not hard-coded here. The actual CSV still needs verification.

The five layers are increasingly selective cuts through susceptibility. Their names do not specify event frequency. The metadata reference assigns:

| Raster tier | Assumed return period | AEP |
|---|---:|---:|
| extreme | 10 years | 10% |
| severe | 25 years | 4% |
| moderate | 50 years | 2% |
| occasional | 100 years | 1% |
| common | 250 years | 0.4% |

The widest footprint is assigned the rarest event. Scores and losses must increase in this order. The system rejects violations; it never sorts losses separately or silently repairs the hazard. Frequencies are assumptions, not local observations. The resulting points are a scenario EP proxy, not a calibrated annual loss distribution. No AAL is reported.

## Modules

| Directory | Responsibility |
|---|---|
| `core/` | constants, numeric safety, money, geography, configuration, errors |
| `exposure/` | schema, CSV loading, validation, anomaly review |
| `hazard/` | provider interface, attached scores, CRS-aware raster sampling, interpretation |
| `vulnerability/` | piecewise damage functions, construction matrix |
| `financial/` | Decimal loss arithmetic, scenario EP checks, accumulation |
| `ai/` | evidence extraction boundary, approval-aware features, ML training, artifact prediction, evaluation |
| `services/` | reproducible pipeline orchestration |
| `storage/` | SQLite analysis snapshots and evidence review |
| `reporting/` | provenance and safe JSON/CSV exports |
| `api/` | FastAPI request schemas, authentication, endpoints |

## API for the future frontend

Use `X-API-Key` if `FLOODCAT_API_TOKEN` is set. `FLOODCAT_ENV=production` refuses startup without a token. This is shared-token prototype authentication; add tenant identity, per-user roles and audit logging before commercial use.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | health/model availability |
| GET | `/v1/model` | configuration and vulnerability matrix |
| POST | `/v1/analyses` | analyse JSON rows, optional enhancement/config |
| POST | `/v1/analyses/csv` | upload CSV text as `csv_text` in a JSON body |
| GET | `/v1/analyses` | recent analyses |
| GET | `/v1/analyses/{id}` | full persisted result |
| GET | `/v1/analyses/{id}/export` | JSON or CSV by run/tier |
| POST | `/v1/evidence/extract` | call configured extraction service |
| POST | `/v1/evidence` | submit geocoded evidence for review |
| GET | `/v1/evidence` | review evidence |
| POST | `/v1/evidence/{id}/approve` | explicit named reviewer approval |

Analysis request:

```json
{"rows": [{"loc_id":"EXAMPLE","lat":-1.28,"lon":36.86,"housing_class":"semi_permanent","tiv_kes":"400000","synthetic":true,"source":"synthetic example","hazard_score_extreme":0.1,"hazard_score_severe":0.2,"hazard_score_moderate":0.3,"hazard_score_occasional":0.4,"hazard_score_common":0.5}],"enhanced":false,"allow_partial":false}
```

Monetary outputs are decimal strings to avoid binary floating-point and JavaScript integer issues. The response includes per-property chains, portfolio curves, construction breakdowns, grid concentration, high-risk TIV, validation issues, configuration fingerprints, AI contribution and provenance. `high_risk_threshold` and grid size are assumptions. Grid cells indicate concentration, not independent events. Results remain immutable snapshots even if evidence changes later, including input/config/model fingerprints, model features/probabilities and approved evidence used at run time.

## Vulnerability and modelling configuration

Defaults use direct score-to-damage piecewise curves with four construction classes. **Numbers are illustrative, not extracted JRC/Huizinga values.** Their shape follows the qualitative Team A guide only. Before submission, replace the values with researched/source-documented adaptations, update `vulnerability_source` and status, and record why each class differs. Do not relabel illustrative defaults as calibrated.

`configs/default.json` contains every factor. Pass `--config` or an API `config` object. Change knots, ceilings, source/status, return periods, enhancement weight, concentration cell size and evidence radius centrally. All constraints are checked.

`assumed_depth` mode scales the curve's normalized axis to `max_depth_m`. Changing that scale alone changes the reported depth but not damage: the same curve is scaled with it. For actual published depth knots, convert each depth to `depth/max_depth_m` and provide corresponding damage values, including defensible endpoints. No default is represented as a genuine physical depth curve.

## AI/ML workflow

1. Acquire independent urban signals and labels, with documented geographic sampling. Known hotspots are positives; unlabeled places are not proven negatives.
2. Prepare labelled feature CSV with `spatial_group`, `split` (train/test), `baseline_common`, `impervious_fraction`, `drainage_deficit`, `evidence_signal`, `label` (0/1).
3. Keep evaluation neighbourhood groups out of training and evidence used as training labels. The code enforces disjoint groups, but you remain responsible for meaningful group boundaries, independence and temporal leakage.
4. Train an interpretable logistic classifier and save coefficients/provenance as JSON. No untrusted executable model pickles.
5. Configure `FLOODCAT_MODEL`, or pass `--model` to the CLI. Enhancement requires impervious and drainage features for every modelled property. Runtime evidence signals are computed from approved evidence; supplied CSV evidence signals cannot override review.
6. Inspect baseline/enhanced hazard and loss changes together with held-out metrics. More hazard/loss is not proof of better accuracy.

```bash
# This demonstrates plumbing only; the labels below are fully synthetic.
python -m floodcat.cli train data/demo/training.csv --output runtime/demo-model.json --provenance 'Illustrative synthetic plumbing test; not Nairobi observations'
python -m floodcat.cli analyse data/demo/exposure.csv --model runtime/demo-model.json --output runtime/enhanced-demo.json
```

Classifier probability means learned hotspot susceptibility, **not AEP**. The conversion uses `activation = max(0, (probability-threshold)/(1-threshold))` and `enhanced = baseline + weight × tier_factor × activation × (1-baseline)`. The default activation threshold is 0.5. This avoids marking every zero-score cell as a hotspot just because a logistic classifier returns a nonzero probability. Both threshold and uplift are explicit uncalibrated assumptions. Tier factors increase with assumed rarity, preserving monotonicity. Out-of-coverage properties cannot receive fabricated enhancement. ML trains only once you run the command; the baseline does not pretend to include AI.

`ai/evaluation.py` supports positive-only hotspot detection comparisons, reporting uncovered points and never fabricating accuracy/false-positive rates. Pair it with independently sampled negative/positive labels for discrimination metrics. Do not report the brief's 12/24 as a measured result from this code without actually loading and sampling the hotspot file.

Evidence extraction expects a server-configured HTTPS service implementing this project's contract; no vendor-specific credentials or model are bundled. It receives `{text, source, instruction}` and returns `{candidates:[{quote,event_date,location_name,confidence,drainage_signal}]}`. Quotes must exist verbatim in input. Candidates are not auto-geocoded or auto-applied. Resolve coordinates and review source reliability/conflicts, then submit and approve. Extraction failures change no model state. See `docs/IMPLEMENTATION_PLAN.md` for the remaining research/integration tasks.

## Validation and operations

Tests cover loss reconciliation, curve constraints, invalid numbers, missing inputs, coverage, duplicate records, partial denominators, API persistence/auth, evidence gating, train/test leakage and raster masks. CI runs the same suite. Docker packaging is provided; deployment has not been performed. SQLite is appropriate for the prototype; move to PostgreSQL/PostGIS and background jobs for large portfolios. Add request-byte limits, rate limits, backups, migrations, secret management and tenant isolation before public hosting. Current API limits row counts, but infrastructure must also bound request bytes.

## Source documents

The architecture and data semantics were read from the attached `Team_A_Nairobi_Problem_Statement.docx`, `Dataset_Metadata.docx`, and `STEP_BY_STEP_GUIDE.md`. No external curve parameters or unseen CSV results were assumed. Original attachments are not copied into this source distribution.
