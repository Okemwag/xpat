# Xpat — Nairobi Urban Flood Model: Approach, Assumptions and Results

**Hackathon Team A · Nairobi Urban Flood Challenge** · Config `nairobi-prototype-v0.5` (fingerprint `9e3ef0bca1cc`) · October 2026

> **Read this first.** Every number in this report is illustrative. The 600 properties are **synthetic**, the hazard layer is a
> **proxy** (not measured flooding), the return periods are **assumptions**, and nothing has been calibrated against Kenyan
> claims. The model's purpose is to make the catastrophe-modelling chain visible, traceable and honest — not to price real risk.

---

## Contents

1. [Summary](#1-summary)
2. [The problem and who it is for](#2-the-problem-and-who-it-is-for)
3. [How the system is built](#3-how-the-system-is-built)
4. [Data sources and provenance](#4-data-sources-and-provenance)
5. [Stage 1 — Hazard](#5-stage-1--hazard)
6. [Stage 2 — Vulnerability](#6-stage-2--vulnerability)
7. [Stage 3 — Exposure](#7-stage-3--exposure)
8. [Stage 4 — Financial engine](#8-stage-4--financial-engine)
9. [Results for the sample portfolio](#9-results-for-the-sample-portfolio)
10. [The AI layer](#10-the-ai-layer)
11. [The interface](#11-the-interface)
12. [Assumptions register](#12-assumptions-register)
13. [Limitations and open questions](#13-limitations-and-open-questions)
14. [Verification and testing](#14-verification-and-testing)
15. [Reproducing the results](#15-reproducing-the-results)
16. [What remains](#16-what-remains)
17. [Glossary](#17-glossary)

---

## 1. Summary

Xpat is a working end-to-end flood catastrophe model for Nairobi: **hazard → vulnerability → exposure → financial engine → loss curve**,
with two AI stages that change the model's inputs, and a web interface that a judge can use live by uploading a CSV.

**Headline results for the 600-property synthetic starter portfolio (KES 63.64 bn insured, gross loss):**

| Measure | Value | Meaning |
|---|---|---|
| 1-in-100 loss (scenario) | **KES 1.70 bn** (2.67% of value) | A loss at least this large has an assumed 1% chance in any year |
| 1-in-100 loss (10,000-year simulation) | KES 1.75 bn (range 1.49–1.84 bn) | Same, read from the simulated year-loss table |
| 1-in-250 loss (scenario) | **KES 2.65 bn** (4.16%) | Assumed 0.4% annual chance |
| Average annual loss | **KES 125.9 m** (simulated 124.7 m, range 119–130 m) | Long-run yearly average |
| Damage-uncertainty range at 1-in-100 | KES 1.01–2.59 bn (5th–95th pct) | If the damage curves are wrong in a plausible way |
| Named flood hotspots flagged by the hazard proxy | **12 of 24** | The proxy cannot see drainage failures |

**Three findings an underwriter should take away**

1. **Value, not fragility, drives this portfolio's loss.** The 84 reinforced-concrete buildings hold 85% of the insured value and
   produce 79% of the 1-in-100 loss; every one of the ten largest property losses is concrete. Informal iron-sheet housing — the most
   fragile class — contributes 0.7%.
2. **The single biggest assumption is how deep a "score of 1" is.** Changing it from 1.5 m to 4 m multiplies every loss by about 2.4.
   The interface makes this a visible control rather than a hidden constant.
3. **Most of the loss is away from the named hotspots** (56% falls more than 2 km from any of them), and the baseline hazard misses
   half of the named hotspots. Both point to the same gap — drainage-driven flooding — which is what the AI evidence stage targets.

**What is AI and what is not.** Gemini is used in two places where a deterministic pipeline cannot help: turning a plain-English
portfolio description into validated records (12 of 12 held-out test cases extracted fully correctly), and turning flood reports into
reviewed, geolocated drainage evidence that raises the hazard where the proxy is blind. The AI never sets a depth, damage ratio or loss
directly; every AI output is re-validated by deterministic code and, for hazard, approved by a named reviewer.

**Status.** The pipeline, both AI features, the uncertainty layers and the interface are built and tested (157 automated tests, plus
headless tests of every interface page and live checks against Gemini). The drainage-evidence library is empty until the team adds
real, independent flood reports; until then no improvement in hotspot detection is claimed.

---

## 2. The problem and who it is for

Kenya has no locally calibrated flood catastrophe model. Flood risk is priced with underwriter judgement and broad global hazard layers,
and there is no public dataset of measured pluvial (surface-water) flood hazard in Nairobi. The brief asks for a prototype that runs a
synthetic portfolio through a documented pipeline, produces a loss and a return-period (EP) curve, uses AI in a way that changes the
output, and is honest about what is real and what is assumed.

| Reader | What Xpat gives them |
|---|---|
| Underwriters & risk analysts | A loss at the return period they budget for, with the assumptions next to it |
| Portfolio / exposure managers | Where insured value and loss are concentrated (map, grid cells, named hotspot areas) |
| Judges | A traceable chain from every portfolio number back to inputs, labelled real / proxy / synthetic / assumption / AI |
| County & disaster bodies | A map of where the baseline hazard is blind, and a route to fix it with local evidence |
| Cedants & brokers | Faster, consistent first-look flood quotes from a CSV or a description |

Out of scope by the brief, and not built: reinsurance treaties, layers, net-of-reinsurance loss, multi-peril aggregation, real policy or
claims data, and physically based hydrology.

---

## 3. How the system is built

### 3.1 Design principles

- **One pipeline, every assumption in one file.** All modelling choices live in `configs/default.json`. Code contains no return
  periods, depths, curve points, caps or policy terms. Changing an assumption is a config edit, or a slider in the interface.
- **Stages talk through fixed tables.** Hazard, vulnerability, exposure and the financial engine are separate modules; orchestration
  sits in `services/`. A better hazard layer, a new portfolio or a different curve each replaces one piece.
- **Fail loudly, never fill with zero.** A property off the hazard maps is an error, not a zero-risk property. Losses that fall as
  events get rarer raise an error instead of being re-sorted.
- **Provenance travels with the numbers.** The `synthetic` flag and `source` survive into every loss row and export; every component
  carries a REAL / PROXY / SYNTHETIC / ASSUMPTION / AI label.
- **Live first.** A judge uploads a CSV and gets results in about 0.1 s after a one-off 0.5 s load. Scripts only rebuild the published
  outputs.

### 3.2 Architecture

```
                 ┌─────────────── services/runtime.Runtime (loaded once) ───────────────┐
 CSV upload ─┐   │  rasters in memory · hotspots · config · store · Gemini · geocoder   │
 AI text ────┼──►│                                                                      │
 sample ─────┘   │  exposure/validation ─► hazard/raster ─► vulnerability ─► financial  │──► results, map, curve, exports
                 │        (contract)        (+ AI uplift)     (JRC curve)    (EP, AAL,   │
                 │                                                          YLT, MC,    │
                 │                                                          policy)     │
                 └──────────────────────────────────────────────────────────────────────┘
        interfaces:  Streamlit app (app/)  ·  FastAPI (src/floodcat/api)  ·  CLI (flood-cat)
```

| Folder | Contents |
|---|---|
| `configs/default.json` | All assumptions (see §12) |
| `src/floodcat/core` | Config validation, constants, errors, geography, numeric helpers |
| `src/floodcat/hazard` | In-memory raster lookup, named hotspots, score validation and the AI uplift |
| `src/floodcat/vulnerability` | JRC depth-damage function, class adjustments, vulnerability matrix |
| `src/floodcat/exposure` | CSV intake, the exposure contract and validation |
| `src/floodcat/financial` | Property loss, EP curve, AAL, accumulation, policy terms, damage Monte Carlo, year-loss table |
| `src/floodcat/ai` | Gemini client, free-text ingestion, evidence extraction, geocoding, evidence rules, evaluation |
| `src/floodcat/services` | Analysis orchestration, live runtime, accounts, sensitivity, data audit |
| `src/floodcat/storage` | Local file store (default) and optional PostGIS repository |
| `app/` | Streamlit interface |
| `scripts/`, `outputs/` | Reproducible published results and the ingestion evaluation |
| `evaluation/` | Held-out test cases for AI ingestion |
| `tests/` | 157 automated tests |

The pipeline runs without a database. PostGIS persistence is optional (`FLOODCAT_DATABASE_URL`).

---

## 4. Data sources and provenance

| Data | Label | What it is | Notes |
|---|---|---|---|
| `nairobi_pluvial_proxy_{extreme,severe,moderate,occasional,common}.tif` | **PROXY** | Five 0–1 flood-susceptibility rasters (~30 m) | Built from Copernicus GLO-30 terrain (basin elevation 45%, local depressions 20%, flatness 15%) and OpenStreetMap rivers (20%). Not depth, not probability, uncalibrated |
| `exposure_nairobi_with_hazard.csv` / `exposure_nairobi_synthetic.csv` | **SYNTHETIC** | 600 generated properties, with and without attached scores | Generated for the starter kit; not a real portfolio |
| `nairobi_hotspots_geocoded.csv` | **REAL** (approximate) | 24 of the county's 37 named flood-prone areas | Names from the March 2026 county list; coordinates are OSM Nominatim neighbourhood centres |
| Huizinga, de Moel & Szewczyk (2017), *Global flood depth-damage functions*, JRC105688, Table 3-1 | **REAL** | Africa residential depth-damage curve | Verified against the report PDF (p.12). Built from South African and Mozambican functions only |
| Return periods, max depth, class adjustments, AAL rules, uncertainty settings, policy terms | **ASSUMPTION** | Modelling choices | All in config, all editable in the interface |
| Flood reports and evidence | **REAL** source, **AI** extraction | Reviewed evidence items | Each keeps its source, verbatim quote and reviewer |
| OpenStreetMap Nominatim | **REAL** (approximate) | Place-name geocoding for AI features | Rate-limited to 1 request/second, cached |

The starter data in `data/` is treated as read-only; derived data goes to `outputs/` and `runtime/`.

---

## 5. Stage 1 — Hazard

### 5.1 What the score is

Each raster cell holds a relative susceptibility score from 0 to 1. **It is not a flood depth and not an annual probability.** A score of 0
means the proxy did not flag that cell — not that it cannot flood.

### 5.2 The tier names are about extremeness, not frequency

The five tiers are threshold cuts of the same susceptibility surface. **"Extreme" keeps only the top 5% of cells** — the narrowest
footprint — so it represents the **most frequent** event; **"common" keeps the top 40%** — the widest footprint — and represents the
**rarest** event. Reading the names the intuitive way would make loss fall as events get rarer. Xpat uses the dataset metadata's
reference mapping:

| Tier | extreme | severe | moderate | occasional | common |
|---|---|---|---|---|---|
| Assumed return period | 1-in-10 | 1-in-25 | 1-in-50 | 1-in-100 | 1-in-250 |
| Annual chance | 10% | 4% | 2% | 1% | 0.4% |

The config validator rejects any mapping that does not increase from extreme to common, and every property's five scores are checked
to be non-decreasing in that order (all 600 starter properties pass).

### 5.3 Looking up each property

Xpat reads the five GeoTIFFs itself (rather than relying on the pre-attached scores) so that **any uploaded location, including AI-described
buildings, is scored automatically**, and an improved hazard layer can be dropped in. The rasters are loaded into memory once (thread-safe,
no open files) and sampled with the same cell rule as rasterio.

**Check:** the lookup reproduces the pre-attached scores for all 600 properties to within 1×10⁻¹⁶. An uploaded file that also carries
scores is compared with the maps; any difference is reported and the map values are used.

**Coverage:** the maps cover longitude 36.60–36.9997 and latitude −1.45 to −1.10. Points outside — including a thin eastern strip inside
the documented bounds but beyond the last raster column — are rejected with a clear message, never scored zero.

### 5.4 How good is the baseline hazard?

At the 24 geocoded named hotspots, the proxy flags (score > 0 in any tier) **12 of 24**: by tier, extreme 1, severe 1, moderate 5,
occasional 9, common 12. The misses — Kibera, Westlands, Lavington, Kileleshwa, Parklands, Kitisuru, Kangemi, Kawangware, Lang'ata,
Madaraka, Donholm, Fedha — are areas where flooding is driven by drainage, which a terrain-and-river proxy cannot represent. 341 of the
600 properties score zero in every tier and so carry no modelled loss.

### 5.5 Named hotspots as context (not exposure)

Each property is tagged with its nearest named hotspot and the distance. For accumulation, a property is grouped under that hotspot only
within 2 km (ASSUMPTION; 217 of 600 properties); otherwise it falls in "no named hotspot within radius". Hotspots are never used as
exposure, and never as training labels.

---

## 6. Stage 2 — Vulnerability

### 6.1 From score to damage

Two steps, both stated:

1. **Score → depth:** `depth = score × max_depth`, with **max_depth = 1.5 m** as the base case (ASSUMPTION). Pluvial flooding in Nairobi
   typically reaches 0.3–1.5 m; the brief's 4 m example is shown as a sensitivity (1, 1.5, 2, 4 m).
2. **Depth → damage:** the published **JRC Africa residential** curve (REAL), adapted per construction class (ASSUMPTION).

| Depth (m) | 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|---|---|
| JRC damage factor | 0.00 | 0.22 | 0.38 | 0.53 | 0.64 | 0.82 | 0.90 | 0.96 | 1.00 |

*Source: Huizinga et al. (2017), Table 3-1, p.12; values checked against the report. Piecewise-linear between points, held at 1.0 beyond 6 m.*

### 6.2 Adapting the curve per construction class

No Kenya-specific curve exists. Each class reads the JRC curve at `depth ÷ scale` and is capped:

| Class | JRC depth scale | Meaning | Damage cap |
|---|---|---|---|
| Informal iron-sheet | 0.5 | Reaches a given damage at half the JRC depth (light walls, contents at floor level) | 95% |
| Semi-permanent | 0.75 | Reaches it at three-quarters of the depth | 90% |
| Permanent masonry | 1.0 | The JRC baseline | 85% |
| Reinforced concrete (RCC) | 1.3 | Needs 1.3× the depth (more resilient) | 80% |

Caps follow the brief's guidance that buildings rarely lose more than 80–95% of value because land and foundations survive; the
validator rejects caps outside 80–95%. At the 1.5 m base depth the caps never bind — the curves do not get that high.

### 6.3 Vulnerability matrix (damage ratio by hazard score, max depth 1.5 m)

| Score | Depth | Informal | Semi-permanent | Masonry | RCC |
|---|---|---|---|---|---|
| 0 | 0.00 m | 0.0% | 0.0% | 0.0% | 0.0% |
| 0.1 | 0.15 m | 13.2% | 8.8% | 6.6% | 5.1% |
| 0.2 | 0.30 m | 25.2% | 17.6% | 13.2% | 10.2% |
| 0.4 | 0.60 m | 44.0% | 31.6% | 25.2% | 20.3% |
| 0.6 | 0.90 m | 59.6% | 44.0% | 34.8% | 28.2% |
| 0.8 | 1.20 m | 71.2% | 55.2% | 44.0% | 35.5% |
| 1.0 | 1.50 m | 82.0% | 64.0% | 53.0% | 42.6% |

Every curve is 0 at no hazard, never decreases, stays at or below its cap, and keeps the fragility order (informal ≥ semi-permanent ≥
masonry ≥ RCC at every score). Tests enforce all four.

### 6.4 Comparison with the brief's reference dashboard (Figure 1)

The reference dashboard feeds the score straight into a saturating curve and tops out at about **85 / 69 / 52 / 31%** (informal /
semi-permanent / masonry / RCC). At a score of 1 Xpat gives **82 / 64 / 53 / 43%**. The fragile classes agree closely; the gap is
reinforced concrete, where we scale the JRC depth axis rather than impose a low ceiling. (The reference's 31% ceiling is itself below
the brief's 80–95% cap guidance, so both are judgement calls.) Because concrete holds most of this portfolio's value, **the RCC setting
moves the portfolio loss more than any other vulnerability choice**; the interface lets a user lower it and see the effect.

We chose a depth-based curve because it is **documented and sourced** (the brief's requirement), it lets underwriters reason in metres,
and it makes the depth assumption explicit and testable instead of buried in a curve shape.

---

## 7. Stage 3 — Exposure

### 7.1 The starter portfolio

| Class | Properties | Insured value | Share of value |
|---|---|---|---|
| Reinforced concrete | 84 | KES 54.14 bn | 85.1% |
| Permanent masonry | 156 | KES 8.45 bn | 13.3% |
| Semi-permanent | 181 | KES 0.85 bn | 1.3% |
| Informal iron-sheet | 179 | KES 0.20 bn | 0.3% |
| **Total** | **600** | **KES 63.64 bn** | |

**Open data question:** in every row, the supplied insured value is about **10× floor area × cost per m²** (ratio 9.97–10.05), and a
separate description of the data gives a total near KES 6.36 bn. The cause is unconfirmed. Xpat uses the supplied values as they are,
flags the gap on every row, and shows the area × cost alternative as a sensitivity (it divides every loss by ten).

### 7.2 The exposure contract

Required: `loc_id`, `lat`, `lon`, `housing_class`, `tiv_kes`, `synthetic`, `source`. Optional: `floor_area_m2`, `cost_per_m2_kes`,
`hazard_score_<tier>`, `deductible_kes`, `limit_kes`. **CSV uploads and AI-ingested rows pass through exactly the same validation.**

### 7.3 What validation handles

| Situation | Behaviour |
|---|---|
| Excel exports (cp1252, UTF-16, byte-order marks), `;` or tab separators, blank lines | Read correctly |
| Header variants (`Latitude`, `lng`, `TIV`, `Construction`…) | Mapped to the contract |
| Class spellings (`concrete`, `RCC`, `mabati`, `brick`, `semi-permanent`…) | Mapped, and reported as a warning |
| Money as `1,250,000`, `KES 2.5m`, `300k`, `Ksh 1bn` | Parsed; anything else rejected |
| Latitude/longitude swapped | Rejected with "lat and lon appear swapped" |
| 0,0 coordinates, points outside the hazard maps | Rejected |
| Duplicate IDs | Later record rejected |
| Real (non-synthetic) portfolio flag | Rejected — out of scope |
| Missing `synthetic`/`source` columns | Rejected unless the user explicitly declares the file synthetic |
| Missing IDs | Rejected unless the user explicitly asks for generated IDs |
| Zero value, shared coordinates, value > 100× median, value ≠ area × cost | Accepted with a warning |
| Invalid deductible/limit | Rejected |
| > 10,000 rows or > 10 MB | Rejected |

If any record fails, the run stops and lists grouped issues; the user must fix them or **explicitly** choose to run on the valid
records, and the result is marked partial with the excluded value reported.

---

## 8. Stage 4 — Financial engine

### 8.1 Scenario losses (the brief's six steps)

For each property and each tier: hazard score → depth → damage ratio → **loss = damage ratio × insured value** → summed to a portfolio
loss per tier. Money uses exact decimal arithmetic. Checks: portfolio loss rises with return period, no damage ratio exceeds its cap,
and the sum of property losses equals every portfolio total and every breakdown total.

### 8.2 Average annual loss (AAL)

The AAL integrates loss over annual exceedance probability with the trapezoid rule through the five points, plus two stated assumptions:
**no loss for floods more frequent than 1-in-2**, and **the 1-in-250 loss held for all rarer floods**. For the sample this gives
KES 125.9 m; the tail beyond 1-in-250 contributes KES 10.6 m. (Hand-checked; a test reproduces it.)

### 8.3 Simulated year-loss table (YLT) and EP curve

The brief's reference dashboard (Figure 3) builds the EP curve from a simulated year-loss table on a log return-period axis with a
bootstrap band, so Xpat does the same as part of the core engine:

- **10,000 simulated years.** Each year draws how rare its worst flood is (annual exceedance probability u ~ Uniform(0,1)) and one
  damage-uncertainty trial (§8.4). Its loss is that trial's scenario curve read at u, interpolated linearly in annual chance between the
  five tier points — the same rule as the AAL — with zero below 1-in-2 and the rarest tier held beyond 1-in-250.
- **EP curve:** the loss at each rarity is the corresponding quantile of the 10,000 year losses, shown from 1-in-1 to 1-in-10,000 on a
  log axis.
- **Band:** 5th–95th percentile from 200 bootstrap re-samples of the simulated years (the "simulation range").
- **Consistency:** the simulated AAL (KES 124.7 m) matches the scenario AAL (KES 125.9 m), and 4,963 of 10,000 years have no loss,
  as the 1-in-2 zero-loss assumption implies.
- **Honest tail:** beyond 1-in-250 the model has no hazard information; the curve keeps rising only because of damage uncertainty. The
  chart marks this edge and the tables label those rows "damage uncertainty only".

### 8.4 Damage-uncertainty Monte Carlo

The damage ratio is the least certain link. For trial k and property b, `z = √ρ·Z_k + √(1−ρ)·ε_kb` and
`ratio = min(cap, mean · exp(σ·z − σ²/2))`, with **σ = 0.4** and **ρ = 0.5** over 2,000 trials (ASSUMPTIONS). The same z applies to every
tier of a property, so each simulated curve still rises with rarity. ρ matters: with fully independent errors (ρ = 0) the 600 errors
largely cancel and the 1-in-100 range shrinks to a misleading KES 1.49–1.95 bn; with ρ = 0.5 it is KES 1.01–2.59 bn. Only damage varies —
hazard, frequency and values are held fixed — so these are **assumption ranges, not confidence intervals**.

### 8.5 Policy terms (optional, off by default)

A simple per-property deductible and limit, as a percentage of insured value or set per row (`deductible_kes`, `limit_kes`):
`insured = min(max(gross − deductible, 0), limit − deductible)`. Turning it on adds an insured EP curve, insured AAL and insured
ranges. Example: a 1% deductible and 50% limit gives a sample 1-in-100 of **KES 1.51 bn insured** against KES 1.70 bn gross. No layers or
reinsurance (out of scope).

### 8.6 Accumulation

Losses and insured value are grouped by construction class, by 1 km grid cell, and by nearest named hotspot (within 2 km), with each
group's share of the loss. The ten largest property losses are listed per scenario.

---

## 9. Results for the sample portfolio

All figures gross, base assumptions, `nairobi-prototype-v0.5`.

### 9.1 Scenario EP points

| Tier | Return period | Annual chance | Loss | % of value |
|---|---|---|---|---|
| extreme | 1-in-10 | 10.0% | KES 263.8 m | 0.41% |
| severe | 1-in-25 | 4.0% | KES 447.2 m | 0.70% |
| moderate | 1-in-50 | 2.0% | KES 1.01 bn | 1.59% |
| occasional | 1-in-100 | 1.0% | KES 1.70 bn | 2.67% |
| common | 1-in-250 | 0.4% | KES 2.65 bn | 4.16% |

### 9.2 Simulated EP curve (10,000 years)

| Rarity | Loss | Simulation range (5–95th pct) | Modelled from |
|---|---|---|---|
| 1-in-10 | KES 293 m | 285–298 m | hazard tiers |
| 1-in-25 | KES 532 m | 499–570 m | hazard tiers |
| 1-in-50 | KES 1.01 bn | 0.87–1.08 bn | hazard tiers |
| 1-in-100 | KES 1.75 bn | 1.49–1.84 bn | hazard tiers |
| 1-in-250 | KES 2.44 bn | 2.21–2.56 bn | hazard tiers |
| 1-in-500 | KES 3.16 bn | 2.62–3.47 bn | damage uncertainty only |
| 1-in-1,000 | KES 3.58 bn | 3.46–3.79 bn | damage uncertainty only |
| 1-in-10,000 | KES 4.38 bn | 3.83–5.68 bn | damage uncertainty only |

### 9.3 Where the loss comes from (1-in-100)

| Class | Properties | Insured value | Loss | Share of loss |
|---|---|---|---|---|
| Reinforced concrete | 84 | KES 54.14 bn | KES 1.34 bn | 78.9% |
| Permanent masonry | 156 | KES 8.45 bn | KES 315.6 m | 18.6% |
| Semi-permanent | 181 | KES 0.85 bn | KES 31.2 m | 1.8% |
| Informal iron-sheet | 179 | KES 0.20 bn | KES 11.1 m | 0.7% |

Largest concentrations near named hotspots: **Mwiki** (15 properties, 17.2% of loss), **Kariobangi** (11, 9.6%), Westlands (7, 4.6%),
Dandora (6, 3.1%). 56.1% of the loss is more than 2 km from any named hotspot. The largest single loss at 1-in-250 is NBO-0316, a
KES 522.7 m concrete building scored 0.627 (0.94 m) → 29.2% damage → KES 152.4 m.

### 9.4 Sensitivity to assumptions

| Scenario | 1-in-100 | 1-in-250 | AAL |
|---|---|---|---|
| Base (1.5 m) | KES 1.70 bn | KES 2.65 bn | KES 125.9 m |
| Max depth 1 m | KES 1.15 bn | KES 1.79 bn | KES 85.5 m |
| Max depth 2 m | KES 2.23 bn | KES 3.48 bn | KES 162.2 m |
| Max depth 4 m (brief's example) | KES 4.11 bn | KES 6.36 bn | KES 290.9 m |
| Insured value = area × cost/m² | KES 170.0 m | KES 264.9 m | KES 12.6 m |
| All return periods doubled | KES 1.70 bn* | KES 2.65 bn* | KES 95.9 m |

\* Doubling the return periods leaves each scenario's loss unchanged but assigns it to a rarer return period (the occasional-tier
loss becomes the 1-in-200 loss), which lowers the AAL.

**Reading this:** the depth assumption and the unresolved 10× insured-value question each move the answer by more than any other
choice. They are therefore the two numbers most worth investigating before using results like these.

---

## 10. The AI layer

The brief requires AI that **materially changes the output**, not just describes it. Both features below change the model's inputs;
neither lets an AI statement become a depth, a damage ratio or a loss.

### 10.1 Feature 1 — Free-text portfolio ingestion

**What it does.** A user writes, e.g., *"20 iron-sheet houses in Mathare, about 300,000 shillings each. A three-storey concrete block of
flats in Kileleshwa insured for 45 million."* Xpat returns 21 validated property records and runs them through the model.

**How it works**

1. Gemini receives the text **as data** (JSON-quoted, with an instruction to ignore embedded instructions) and returns structured groups
   against a strict JSON schema: place, class (or "unknown"), count, area, rate, value each or group total, and a verbatim quote.
2. Deterministic code then:
   - **checks every quote is actually in the text** (flags it if not);
   - **geocodes the place with OpenStreetMap Nominatim** (an AI coordinate estimate is used only as a flagged fallback);
   - splits group totals per building; computes value from area × rate when given;
   - fills missing size/rate from the **starter portfolio's class medians**, labelled ASSUMPTION;
   - never guesses a class — an unstated class is flagged for the user to choose;
   - caps groups (≤500 buildings each, ≤2,000 total) so a prompt cannot create a huge portfolio.
3. The user sees what the AI understood, every flag and the source of every field (AI / Nominatim / ASSUMPTION), edits the rows, and
   only then runs them — through **the same validation as a CSV**.

**Evidence of what it contributes.** A held-out set of 12 team-written synthetic descriptions (`evaluation/ingestion_cases.json`,
never shown to the model as examples) covers simple and multi-group portfolios, group totals, area × rate, numbers in words, Swahili
terms ("mabati"), a missing value, a missing class, given coordinates, irrelevant text and a **prompt-injection attempt**. Scored
automatically (`make eval-ingestion`):

| Measure | Result |
|---|---|
| Cases fully correct | **12 / 12** |
| Groups found | 15 / 15 |
| Housing class right (incl. correctly flagged unknown) | 15 / 15 |
| Building count right | 15 / 15 |
| Value per building within 2% | 14 / 14 |
| Places located | 15 / 15 |
| Quotes found in the text | 15 / 15 |
| Spurious extra groups (incl. the injection) | 0 |

*Models used: gemini-3.5-flash (8 cases), gemini-3.8-flash (4). This is a small check of a first draft, not a statistical accuracy
estimate; the descriptions are fairly clean, and every AI record is still reviewed by a person before it is modelled. Harder cases written
by someone other than the prompt author would strengthen it.*

**Known difference:** an AI-described building without a stated value is valued at area × cost, while the starter portfolio's values are
about 10× that (§7.1). The two sources therefore value buildings on different bases until the 10× question is resolved.

### 10.2 Feature 2 — Drainage evidence to improve the hazard

**Why.** The baseline hazard flags 12 of 24 named hotspots; the misses flood because of drainage, which terrain and rivers cannot show.
Local reports describe exactly these floods, but as unstructured text.

**How it works**

1. **Extract.** A user pastes a report and its source. Gemini proposes places, dates, mechanism (drainage, surface runoff, river
   overflow, other, unknown), confidence and a verbatim quote. Candidates whose quote is not in the report are **dropped**; places are
   geocoded with Nominatim.
2. **Review.** Every candidate enters the library **unapproved**. A user with the reviewer role checks it, corrects the location or
   mechanism, and records whether the source is **independent of the county hotspot list**. Only a named reviewer can approve.
3. **Apply (switchable, off by default).** Approved evidence of a drainage or surface-runoff mechanism with confidence ≥ 0.5 raises the
   hazard within 1 km, fading linearly with distance:
   `s' = 1 − (1 − s)·(1 − w·f_tier·signal)`, with w = 0.25 and tier factors 0.2 (extreme) to 1.0 (common) (ASSUMPTIONS). This lifts a
   score by at most 25% of its remaining headroom, more in rarer tiers, keeps scores within 0–1, and **preserves the tier order**
   (proved and tested). River-overflow reports are excluded because the proxy already models rivers. Overlapping reports do not stack.
4. **Measure.** The interface shows the before/after loss curves, the AAL change, which properties changed (near vs away from named
   hotspots), and the **named-hotspot hit rate before and after — counting only evidence marked independent**, because evidence copied
   from the county list would make the check circular.

**Status and evidence.** The pipeline is built and tested end to end, including live Gemini extraction (a test passage produced Kibera
as drainage dated 2024-04-24 and Mathare as river overflow, which is correctly excluded from the uplift). **The evidence library is
currently empty of real reports**, so no improvement is claimed yet. In a scratch test with one manual drainage item at Kibera, six
properties changed, AAL rose by KES 0.53 m and the hit rate moved from 12 to 14 of 24 — which demonstrates the mechanics, not accuracy.

**Caveats stated in the interface:** the hotspot check is positive-only (there is no list of places known not to flood, so false alarms
cannot be measured); hotspot coordinates are approximate; evidence near a hotspot flags it by construction, so the real test is whether
independent reports exist for the places the proxy misses; and a higher loss is never presented as proof of a better model.

### 10.3 Gemini integration and safeguards

- Model chain: `GEMINI_MODEL` (optional), then gemini-3.8-flash → gemini-3.5-flash → gemini-flash-latest. Rate-limit and overload errors
  are retried; a retired or busy model falls through to the next; the model that actually answered is recorded on every AI output.
  (gemini-2.5-flash is no longer available to new keys — the reason for the chain.)
- Temperature 0 and a strict JSON schema; responses are parsed and re-validated; malformed or blocked responses change nothing.
- Without a key the app runs normally and says where AI would appear. Tests use fake Gemini and geocoder objects and never call the
  network.

---

## 11. The interface

A Streamlit web app (`make app`, http://localhost:8501).

### 11.1 User journeys

1. **Arrive** — a landing page explains the product in plain words, shows a live preview computed from the sample portfolio, and offers
   *Create account*, *Sign in* or *Explore as guest* (for judges; no account needed).
2. **Load a portfolio** — upload a CSV (template provided), describe it in words (AI), or use the sample. Validation issues are grouped
   ("tiv mismatch — 600 records") with examples; declarations and partial runs are explicit choices.
3. **Read the result** — Overview: total value, 1-in-100 and 1-in-250 loss, AAL, each with a one-line meaning; the simulated loss curve;
   loss by class; where loss concentrates; the AI effect.
4. **Drill down** — Loss curve (log axis to 1-in-10,000, band, plain-English table), Exposure & hazard map, Property explorer (the full
   calculation for one building).
5. **Question the assumptions** — change max depth, return periods, class curves, AAL rules, hotspot radius, policy terms and uncertainty
   settings; re-run instantly; run sensitivity scenarios.
6. **Improve the hazard with AI** — extract, review, approve, apply, compare.
7. **Check honesty** — provenance of every component, data sources, the 12-of-24 hit/miss map, AI accuracy, limitations.
8. **Keep and share** — every run is saved; download a Markdown summary, the full JSON report, or property-level CSVs.

### 11.2 Explainability built in

- **The three reference figures are reproduced:** the damage matrix against hazard score with the reference values marked (Figure 1);
  the map with size = value, colour = hazard score and a tooltip that traces *class → value → score → depth → damage → loss* with the
  arithmetic, e.g. "Loss = KES 522.6 m × 29.2% = KES 152.4 m" (Figure 2); and the EP curve from 10,000 simulated years on a log axis
  with a grey band and tooltips such as "1-in-500 year loss: KES 3,157,651,032" (Figure 3).
- **Every chart has a three-line caption:** what it shows, how to read it, and where it comes from (with REAL / PROXY / SYNTHETIC /
  ASSUMPTION / AI badges).
- **A pipeline strip** (Hazard → Vulnerability → Exposure → Financial engine → Loss curve) links each stage to its view.
- **The Methods page** explains the four stages, what a return period is and is not ("about a 1% chance each year, not once a
  century"), why tier names do not match frequency, and how the simulation works.

### 11.3 Accounts and roles

Local accounts with PBKDF2-SHA256 password hashing, password rules, login throttling and three roles: **analyst** (run and view),
**reviewer** (also approve AI evidence) and **admin** (also manage users). Guests get a temporary session (reviewer role by default so a
judge can try the evidence workflow; configurable). This is demo-grade authentication, not production identity management.

---

## 12. Assumptions register

Every assumption is in `configs/default.json` and editable in the interface unless noted.

| # | Assumption | Value | Label | Why | Effect if wrong |
|---|---|---|---|---|---|
| A1 | Tier → return period | 10 / 25 / 50 / 100 / 250 yr | ASSUMPTION | Dataset metadata reference mapping | Relabels the curve; AAL scales roughly inversely |
| A2 | Score → depth | depth = score × 1.5 m | ASSUMPTION | Typical Nairobi pluvial depths 0.3–1.5 m | Largest single lever: 1 m → ×0.68, 4 m → ×2.4 |
| A3 | Base damage curve | JRC Africa residential, Table 3-1 | REAL | Published, documented, the brief's reference | Built from two countries' data |
| A4 | Class depth scales | 0.5 / 0.75 / 1.0 / 1.3 | ASSUMPTION | Relative fragility of construction | RCC scale dominates this portfolio's loss |
| A5 | Damage caps | 95 / 90 / 85 / 80% | ASSUMPTION | Brief's 80–95% guidance | Do not bind at 1.5 m |
| A6 | Loss | damage ratio × insured value | ASSUMPTION | Brief's method | — |
| A7 | Insured value | supplied `tiv_kes` (≈10× area × cost) | SYNTHETIC | Keep results traceable to the file | Area × cost would divide losses by 10 |
| A8 | No loss below | 1-in-2 | ASSUMPTION | Very frequent floods assumed to cause no insured loss | Raises/lowers AAL; half of simulated years are zero |
| A9 | Tail beyond rarest tier | hold the 1-in-250 loss | ASSUMPTION | No information on rarer floods; avoids invention | Likely understates extreme tail |
| A10 | Interpolation between points | linear in annual chance | ASSUMPTION | Same rule for AAL and YLT | Small effect between points |
| A11 | Year-loss table | 10,000 years, 200 bootstraps, 5–95% band, fixed seed | ASSUMPTION | Matches the reference dashboard; reproducible | Band reflects sampling, not model error |
| A12 | Damage uncertainty | σ = 0.4, ρ = 0.5, 2,000 trials | ASSUMPTION | Judgement; no claims to fit | Range width scales with σ and ρ |
| A13 | Policy terms | off; 0% deductible, 100% limit | ASSUMPTION | Brief asks for gross loss; terms optional | Lowers insured loss when on |
| A14 | Hotspot grouping radius | 2 km | ASSUMPTION | Few properties within 1 km of each hotspot | Changes accumulation groups only |
| A15 | Grid cell | 1 km | ASSUMPTION | Simple, transparent accumulation unit | Changes accumulation groups only |
| A16 | Evidence radius | 1 km, linear fade | ASSUMPTION | Neighbourhood-scale drainage effects | Width of AI uplift |
| A17 | Evidence uplift | w = 0.25; tier factors 0.2–1.0 | ASSUMPTION | Bounded, order-preserving adjustment | Size of AI effect |
| A18 | Evidence used | drainage & surface runoff, confidence ≥ 0.5, approved | ASSUMPTION | Mechanisms the proxy cannot see | What changes hazard |
| A19 | AI-filled sizes | starter class medians | ASSUMPTION | Only reference available | Values for under-described buildings |
| A20 | Coverage | raster extent only | — (rule) | Never assume zero hazard | Points outside are rejected |

---

## 13. Limitations and open questions

**Model**
- The hazard is a terrain-and-river proxy, not a flood model; it is blind to drainage and flags 12 of 24 named hotspots.
- The five tiers are threshold cuts of one surface, so the "events" are nested footprints, not independent physical floods.
- Return periods are assumed, not derived from rainfall statistics; the EP curve compares assumed scenarios rather than forecasting.
- The vulnerability curve is a regional curve adapted by judgement, not validated against Kenyan claims.
- Nothing beyond 1-in-250 is modelled; the far tail reflects only damage uncertainty.
- Uncertainty ranges cover damage only (and sampling, for the band) — not hazard, frequency or values.
- A zero score is not "cannot flood"; hotspot coordinates are approximate neighbourhood centres.

**Data**
- The portfolio is synthetic. Its insured values are ≈10× area × cost for an unconfirmed reason; this changes every loss by a factor
  of ten and should be resolved with the data owner.
- 13 of the county's 37 named areas still need sourced coordinates.

**AI**
- The ingestion check is small and team-written (12 cases); a larger, independently written set is needed for a real accuracy claim.
- The evidence feature has no real reports in its library yet; the hit-rate check can only measure detection of known flood areas, not
  false alarms.
- Gemini model availability changes; the fallback chain mitigates this but outputs may differ between models.

**Interface and operations**
- Accounts and runs are stored locally; on a host with ephemeral disk they reset on restart.
- Authentication is demo-grade. The app is not deployed publicly; hosting and secret management are open decisions.

---

## 14. Verification and testing

**157 automated tests** (`make test`), including the invariants the project requires:

| Invariant | Tested |
|---|---|
| Portfolio loss rises with return period (scenario, insured, simulated) | ✓ |
| Damage ratio within [0, cap], monotonic, zero at no hazard, fragility order kept | ✓ |
| Sum of property losses equals every portfolio and breakdown total | ✓ |
| Raster lookup reproduces the pre-attached scores (600/600) | ✓ |
| The synthetic label survives into every loss row and export | ✓ |
| CSV and AI rows pass the same validation | ✓ |
| AAL matches a hand calculation; YLT mean matches AAL; zero-loss share matches the assumption | ✓ |
| Monte Carlo reproducible, brackets the scenario loss, collapses at σ = 0, widens with ρ | ✓ |
| AI uplift keeps scores in 0–1 and tier order; only approved, confident drainage evidence applies | ✓ |
| Gemini fallback, retry, malformed and blocked responses; quote checks; abusive responses rejected | ✓ |
| Upload edge cases (≈30 cases), accounts, lockout, roles, path traversal, API | ✓ |
| The real upload page with clean, faulty, unlabelled and non-CSV files | ✓ |

Beyond the suite: every interface page was driven headlessly signed-out, signed-in, before and after a run, with policy terms and AI
evidence applied (no exceptions); the JRC values were checked against the source PDF; the AAL was checked by hand; and both AI features
were exercised live against Gemini.

---

## 15. Reproducing the results

```bash
make install          # dependencies (uv): dev, geo, ui, ai extras
make test             # 157 tests
make outputs          # rebuild outputs/ (Day 1 tables, EP, YLT, ranges, sensitivity)
make eval-ingestion   # re-score AI ingestion (needs GEMINI_API_KEY)
make app              # interface at http://localhost:8501
```

Every analysis stores its config fingerprint, input fingerprint, hazard provider, declarations and the evidence snapshot it used.
Simulations use fixed seeds, so results are identical between runs with the same config. Published files in `outputs/` state their
inputs, assumptions and generation date and are never hand-edited.

---

## 16. What remains

| Item | Why it matters |
|---|---|
| Collect real, independent flood reports and run the evidence workflow | Turns the AI hazard feature from demonstrated to evidenced; the main differentiator |
| Resolve the 10× insured-value question with the data owner | Changes every loss by a factor of ten |
| Harder ingestion test cases written by someone other than the prompt author | Strengthens the AI accuracy claim |
| Decide hosting (public link vs local), secret storage and persistent accounts | Needed if judges test remotely |
| Visual review of the interface in a browser (layout, dark mode, phone width) | Pages are tested for errors, not yet for appearance |
| Rehearse the demo with a prepared CSV and description | The two-minute understanding test |

---

## 17. Glossary

| Term | Meaning |
|---|---|
| **AAL** | Average annual loss — the long-run yearly average loss |
| **Accumulation** | Many insured properties exposed to the same event |
| **Annual exceedance probability** | The chance in any year that a loss of at least a given size happens |
| **EP curve** | Loss plotted against how rare it is |
| **Return period** | 1 ÷ annual exceedance probability; "1-in-100" ≈ 1% a year, not once a century |
| **Year-loss table (YLT)** | Many simulated years, each with its loss; the EP curve is read from it |
| **Bootstrap band** | Range obtained by re-sampling the simulated years; shows sampling variability |
| **Damage ratio** | Share of a building's value destroyed |
| **Proxy** | A stand-in measure built from real inputs but not measuring the thing itself |
| **Pluvial flood** | Surface-water flooding from rain the ground and drains cannot carry away |
| **JRC / Huizinga curves** | Published global depth-damage functions from the EU Joint Research Centre |
| **RCC** | Reinforced concrete construction |
| **Deductible / limit** | The part of a loss the owner keeps / the most the policy pays |
