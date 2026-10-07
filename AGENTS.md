# AGENTS.md

Guidance for any coding agent (or new teammate) working in this repository.
Read this file fully before changing code, data, configs or outputs.

---

## 1. What this project is

**Nairobi Urban Flood Challenge — Team A.** A catastrophe (CAT) model for
urban, surface-water (pluvial) flooding in Nairobi, built for a 3-day hackathon.

The model follows the chain required by the problem statement:

```
Hazard → Vulnerability → Exposure → Financial engine → Loss (EP) curve
```

and must add **one AI stage that materially changes the model's output**
(not just a description of results).

### Who the output is for
Design every user-facing output for these readers, not for engineers:

| Reader | What they need |
|---|---|
| Underwriters & risk analysts | A defensible loss estimate and return period they can budget with, quickly |
| Portfolio / exposure managers | Accumulation: how much insured value sits where flooding is worst |
| Hackathon judges | Modelling rigour, genuine AI use, honest limitations |
| County & disaster-management bodies | A tool they could eventually use publicly |
| Cedants & brokers | Faster, more consistent flood quotes |

A non-modeller must understand the results interface in **under two minutes**.

### The five objectives (non-negotiable)
1. End-to-end pipeline: ingest hazard → apply vulnerability → loss per property
   → aggregate by return period → financial engine → loss / return-period curve.
2. AI that materially enhances the result.
3. A return-period (EP) loss curve understandable by a non-modeller.
4. Every assumption and every use of synthetic data stated clearly. Never
   present placeholder numbers as real observations.
5. An interface any stakeholder above could open and understand.

Every change should move at least one of these forward. If a change does not,
question whether it belongs in a 3-day build.

---

## 2. Repository map

```
app/                        Streamlit interface (live use: upload → results)
  streamlit_app.py           entry point, navigation, auth gating
  ui/                        session state, components, charts
  views/                     one file per page
configs/default.json        Single source of truth for model assumptions
data/                       Starter kit (read-only, see §4)
migrations/                 Alembic migrations (PostGIS, optional)
outputs/                    Generated CSV/MD results (reproducible, see §6)
runtime/                    Generated reports and the local store (gitignored)
scripts/                    Build scripts that produce outputs/
src/floodcat/
  core/          config, constants, errors, geo, numeric helpers
  hazard/        raster lookup (in-memory), providers, hotspots, score interpretation
  vulnerability/ damage (depth-damage) functions
  exposure/      loaders, models, schema validation (the contract for CSV and AI rows)
  financial/     loss, EP curve + AAL, accumulation
  ai/            gemini client, ingestion, extraction, geocode, evidence, evaluation
  services/      analysis orchestration, runtime (live context), accounts, sensitivity, data audit
  reporting/     export, provenance, markdown summary
  storage/       local file store (default), repository (PostGIS, when FLOODCAT_DATABASE_URL is set)
  api/           HTTP app + schemas
  cli.py         command-line entry point
tests/                      pytest suite
```
Stage boundaries matter: each stage talks to the next only through tables /
typed models. Do not reach across stages (e.g. vulnerability code reading
rasters, or the API recomputing damage itself). Orchestration belongs in
`services/`.

---

## 3. Modelling rules (get these right — judges will check)

### 3.1 Hazard tiers ↔ return periods — DO NOT INVERT
Tier names describe **how extreme a cell is, not how often it floods**.
`common` keeps the top 40% of cells (widest footprint = **rarest** event);
`extreme` keeps the top 5% (narrowest = **most frequent**).

| Tier | extreme | severe | moderate | occasional | common |
|---|---|---|---|---|---|
| Return period (assumed) | 10 yr | 25 yr | 50 yr | 100 yr | 250 yr |

- This mapping is an **assumption** (taken from the reference dashboard in the
  dataset metadata). It lives in `configs/default.json`, never hard-coded.
- Portfolio loss **must rise as return period increases**. A test enforces it.

### 3.2 The hazard value is a score, not a depth
- Values are 0–1 relative susceptibility. `0` = dry (there is no separate
  no-data value for Nairobi rasters).
- Never call the score a depth. If converting (`depth = score × max_depth`),
  `max_depth` is a labelled assumption in config, and the interface must show
  results are sensitive to it.
- Score is built from real terrain (Copernicus GLO-30) and real rivers (OSM)
  but is **not calibrated hydrology** and knows nothing about drainage.

### 3.3 Vulnerability
- Reference: JRC / Huizinga global depth-damage functions (Africa,
  residential). Cite the source table in docs and in code docstrings.
- One curve per `housing_class`:
  `informal_iron_sheet`, `semi_permanent`, `permanent_masonry`, `concrete_rcc`.
- Damage ratio must be monotonic non-decreasing with severity, 0 at no hazard,
  and **capped at 80–95%** of value depending on class. Never 100%.
- Every way our parameters differ from JRC is written down (config + docs).
- Also produce the **vulnerability matrix** (housing class × severity band →
  damage ratio) — the problem statement asks for it.

### 3.4 Exposure
- The portfolio is **synthetic**. Keep the `synthetic` and `source` columns
  through every filter, join and export so the label reaches the results.
- The supplied `tiv_kes` is ≈ **10 ×** floor_area_m2 × cost_per_m2_kes in every
  row (total KES 63.64 bn). The cause is unconfirmed. Use the supplied value as is,
  keep the `tiv_mismatch` warning, and show area × cost only as a sensitivity.
  Currency is KES; coordinates are WGS84 (EPSG:4326).
- The validated exposure schema is the **contract** for any AI ingestion: AI
  output must pass the same validation as the CSV.
- Hotspots (`nairobi_hotspots_geocoded.csv`) are for **validation only**,
  never exposure. Names are real; coordinates are approximate (OSM Nominatim).

### 3.5 Financial engine
Per building, per tier: hazard → damage ratio → `damage_ratio × tiv_kes` →
sum to portfolio loss → EP curve across return periods.
- Report: loss per return period, average annual loss (AAL, with the
  integration assumptions stated), loss by housing class, top locations,
  loss as % of total insured value, accumulation by area.
- Base result is **gross insured loss**. Simple per-risk policy terms
  (deductible / limit) may exist in config, default off.
- **Out of scope:** reinsurance treaty structuring, layers, net-of-reinsurance
  loss, multi-peril aggregation, real policy/claims data. Do not build these.

### 3.6 Known limitation to be honest about
The proxy flags **12 of 24** named hotspots. The 12 misses (Kibera, Westlands,
Lavington, …) flood because of drainage, which the proxy cannot see. Any
hazard improvement must report its own hit rate against the same 24 places in
the same plain terms.

---

## 4. Data rules

- `data/` is the starter kit. **Treat it as read-only.** Never edit, overwrite
  or "fix" these files; write derived data to `outputs/` or `runtime/`.
- Do not add any real client, policy or claims data to the repo.
- If you regenerate or extend the portfolio, write it to a new file, label it
  synthetic in-file, and record how it was generated (seed, method).

---

## 5. Provenance labelling

Every number shown to a user carries one of these labels (see
`reporting/provenance`):

| Label | Meaning |
|---|---|
| `REAL` | Observed / published data (e.g. hotspot names, terrain, JRC curve points) |
| `PROXY` | Derived from real inputs but not a measurement (hazard score) |
| `SYNTHETIC` | Generated for this hackathon (exposure portfolio) |
| `ASSUMPTION` | A modelling choice we made (return periods, max depth, class adjustments) |
| `AI` | Produced or changed by the AI stage, with evidence of what changed |

If you add an output and cannot say which label applies, stop and resolve that
before shipping it.

---

## 6. Working conventions

### Environment
- Python project managed with **uv** (`pyproject.toml`, `uv.lock`).
  - Install: `uv sync`
  - Run anything: `uv run <command>`
- Check the `Makefile` for project shortcuts before inventing new commands.
- PostGIS (`storage/repository.py`, `migrations/`) is optional and used only
  when `FLOODCAT_DATABASE_URL` is set. The pipeline, API and interface must
  **run without a database**; keep it that way.
- Live use: judges upload CSVs in the Streamlit app (`make app`). Every
  feature must work in-process through `services/runtime.Runtime`; scripts in
  `scripts/` only rebuild the published `outputs/`.

### Configuration
- All assumptions live in `configs/default.json`. No magic numbers in code
  for return periods, depths, curve points, caps or policy terms.
- Adding an assumption = add it to config + document it + label it
  `ASSUMPTION`.

### Outputs
- Everything in `outputs/` and `runtime/` must be reproducible from a script
  in `scripts/` (or the CLI) plus config. Never hand-edit generated files.
- Each generated Markdown output states its inputs, assumptions and the date
  generated.

### Tests
- Run `uv run pytest` before considering any change done. CI runs the same
  suite (`.github/workflows/test.yaml`).
- Invariants that must always have a test:
  1. Portfolio loss rises with return period.
  2. Damage ratio ∈ [0, class cap], monotonic in severity, 0 at no hazard.
  3. Sum of building losses = portfolio loss for every scenario.
  4. Raster lookup reproduces the pre-attached scores in
     `exposure_nairobi_with_hazard.csv`.
  5. The `synthetic` label survives into every exported exposure/loss table.
  6. Exposure from any source (CSV or AI) passes the same schema validation.
- Add a test for every bug you fix.

### Code style
- Small pure functions; vectorised pandas/numpy over Python loops.
- Type hints on public functions; docstrings cite sources for any published
  parameter.
- Fail loudly with errors from `core/errors` rather than silently filling
  defaults.

---

## 7. AI stage

Two AI features, both Gemini (`ai/gemini.py`, model from `GEMINI_MODEL`), both
optional at runtime (no key → the app says AI is off; everything else works):

1. **Free-text exposure ingestion** (`ai/ingestion.py`): description → groups →
   rows. Quotes are checked against the input; places are geocoded with
   Nominatim (AI estimate only as a flagged fallback); missing size/value is
   filled from starter-portfolio class medians (ASSUMPTION). Rows must pass
   `exposure/validation.py` unchanged — the same contract as CSV uploads.
2. **Drainage-evidence hazard adjustment** (`ai/extraction.py`,
   `ai/evidence.py`, `hazard/interpretation.enhance`): reports → candidate
   evidence with verbatim quotes → human approval by a named reviewer →
   uplift `s' = 1 − (1 − s)(1 − w·f_tier·signal)` near approved drainage /
   surface-runoff evidence. Off by default (`ai_adjustment=False`).

Rules:
- Gemini output is untrusted data. Re-validate everything deterministically;
  never let it set a depth, damage ratio or loss directly.
- Report the effect as before/after numbers (loss per return period, AAL,
  changed properties) **and** the named-hotspot hit rate before/after.
- The hit-rate check uses only evidence marked `independent_of_hotspot_list`.
  Evidence derived from the county hotspot list makes the check circular.
- A higher loss is not evidence of a better model. Never claim accuracy.
- Tests use fake LLM and gazetteer objects; no test may call the network.
- An LLM-written summary of results on its own does **not** satisfy the brief.

---

## 8. Definition of done (for any task)

- [ ] Change serves one of the five objectives.
- [ ] Assumptions in config and documented; outputs labelled (§5).
- [ ] `uv run pytest` passes; new behaviour has a test.
- [ ] Generated outputs rebuilt from scripts, not hand-edited.
- [ ] Nothing out of scope (§3.5) added.
- [ ] Plain-English explanation ready for a non-modeller where the change is
      user-visible.

## 9. Don'ts

- Don't invert the tier → return-period mapping.
- Don't call a hazard score a flood depth.
- Don't present synthetic or assumed values as real.
- Don't modify files in `data/`.
- Don't build reinsurance layers/treaties or multi-peril features.
- Don't commit secrets; use `.env` (template in `.env.example`).