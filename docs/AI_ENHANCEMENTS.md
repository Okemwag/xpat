# AI enhancements

Eight additions to the platform. Each one keeps the rule from AGENTS.md §7: AI output is untrusted data, checked by
deterministic code, labelled, and never allowed to set a depth, damage ratio or loss directly. Every setting below is an
ASSUMPTION in `configs/default.json`. Assumption sets saved before these settings existed are filled from those defaults
(`core/config.merge_defaults`). Existing values are never changed.

| # | Feature | Who it helps | Code | Page | Labels |
|---|---|---|---|---|---|
| 1 | Drainage-aware hazard | Judges, county teams, underwriters | `hazard/drainage.py`, `scripts/build_drainage_layers.py` | Hazard checks → Drainage model | PROXY, ASSUMPTION (prior) or AI (learned) |
| 2 | Evidence harvester | Risk analysts, reviewers | `ai/harvest.py` | AI flood evidence → Harvest news | AI, reviewer-approved |
| 3 | Satellite flood check | Judges, county teams | `hazard/satellite.py`, `scripts/gee_sentinel1_flood.js` | Hazard checks → Satellite flood check | REAL (flood map), PROXY (comparison) |
| 4 | Building storeys from imagery | Exposure managers, brokers | `exposure/buildings.py`, `scripts/gee_open_buildings_height.js` | Portfolio → before running | AI, user-accepted |
| 5 | Schedule quality reviewer | Cedants, brokers, underwriters | `exposure/quality.py`, `ai/quality.py` | Portfolio → before running | ASSUMPTION (checks), AI (explanations) |
| 6 | Ask the results | Everyone | `ai/ask.py`, `app/ui/ask_view.py` | Overview, Loss curve | AI wording, figures from the model |
| 7 | Referral and quote memo | Underwriters, heads of underwriting | `ai/memo.py`, `app/ui/memo_view.py` | Underwriting decision | AI wording, decision from rules |
| 8 | Public risk notes (English and Kiswahili) | County and disaster teams | `hazard/area.py`, `ai/public_note.py` | Public risk notes | PROXY, REAL, AI |

## 1. Drainage-aware hazard

**Why:** the baseline proxy finds 12 of 24 named hotspots. The places it misses (Kibera, Westlands, Lavington, …) flood
through drains. WRI's review of the 2024 floods names blocked drains, solid waste and spreading hard surfaces as causes
([WRI 2026](https://www.wri.org/research/flooding-nairobis-informal-settlements)).

**Features** (each scaled 0–1): the baseline common-tier score; OSM building density within `density_radius_m`
(saturating at `density_saturation`), standing in for sealed ground; distance to the nearest mapped
`waterway=drain|ditch` over `drain_reach_m`; and closeness to a `tunnel=culvert` within `culvert_reach_m`.

**Model:** p = logistic(intercept + Σ wᵢxᵢ).
- **Prior:** weights are `prior_weights` and `prior_intercept` (ASSUMPTION). Used until there are at least
  `min_training_positives` approved, independent drainage or runoff reports.
- **Learned:** L2-regularised logistic regression (`l2`). Reports are the positives. `background_points` random points
  (seed `seed`), kept `background_exclusion_m` away from any report, are the pseudo-absences. Sampled satellite flood pixels
  can be added as positives. **The 24 hotspots are never used for training**; they are the test.

Hazard is raised only where p > `probability_threshold`, with signal = (p − t)/(1 − t). The uplift uses the same formula as
evidence (`hazard/interpretation.enhance`), with its own `weight`. Results appear as the "enhanced" run beside the
unchanged baseline, and as the hotspot hit rate before and after, under the same rule (score > 0).

**Limits:** OSM maps drains unevenly. In informal areas a drain gap can mean nobody mapped the drain. A higher hit rate
does not show accuracy: the uplift also raises places that do not flood.

**Build the layers.** Two ways; both write `runtime/drainage/osm_layers.json` (gitignored):

- **Faster (recommended):** `uv run --with osmium python scripts/build_drainage_layers.py --geofabrik`. This downloads the
  Geofabrik Kenya extract once (about 350 MB, resumable) and cuts the Nairobi box out locally; it takes minutes.
- **Overpass API:** `uv run python scripts/build_drainage_layers.py`. The public servers are shared and often busy, so this
  can take an hour or more. It retries, switches servers, splits dense tiles and resumes from saved tiles.

Check the result with `uv run --extra geo flood-cat drainage-check`. On the October 2026 extract, OSM held 282 drain lines,
198 culverts and 612,210 buildings in the box. The prior weights flag 21 of 24 named hotspots, against 12 for the map
alone, and raise hazard at about 18% of random points across the city. Building density does most of the work, and drains
are too sparsely mapped to separate places. Treat this as a prior to be replaced by learned weights, not as a validated
improvement.

## 2. Evidence harvester

Saved searches (`evidence_harvest.queries`) go to the [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/),
limited to Kenyan outlets and English, over `timespan`, at most `max_articles` new articles per run. Each article is passed
through the existing `ai/extraction.extract`: contact details are removed, the quote must appear verbatim, and places are
geocoded. Every candidate is **unapproved**, and a named reviewer still approves it.

- Only public http(s) addresses are fetched, including after redirects, with size and time limits.
- Articles already in the library, and duplicates by URL or title, are skipped.
- An article naming `hotspot_list_threshold` or more places from the county list, or using list wording, is marked
  **not independent**, so it cannot inflate the hit-rate check. The reviewer can change this flag.
- Each article read uses one AI request against the organisation's quota. Only the link, the quote and the place are kept.

## 3. Satellite flood check

`scripts/gee_sentinel1_flood.js` follows the
[UN-SPIDER Sentinel-1 practice](https://un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping/step-by-step):

- VH ratio of after ÷ before above 1.25
- 50 m smoothing
- permanent water and slopes over 5% masked
- specks of 8 pixels or fewer removed

By default it runs on the March–May 2024 rains. The page or `flood-cat satellite-check` then samples `sample_points`
flooded and dry pixels (seed `seed`) and reports two numbers per tier: how often the map flags flooded pixels (hit rate) and
how often it flags dry pixels. Read the two together; neither is an accuracy.

The method is change detection, not AI. It is the independent test for features 1 and 2. When the drainage model is
compared on the same map, it is fitted **without** that map's pixels. Radar misses water among buildings, so read the
results mainly along the river corridors.

## 4. Building storeys from imagery

`scripts/gee_open_buildings_height.js` exports building height from
[Open Buildings 2.5D Temporal v1](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1)
(0–100 m above terrain, yearly 2016–2023, about 4 m effective resolution, CC-BY 4.0 or ODbL). The heights come from a
machine-learning model, and no accuracy figure is published for them.

For rows with a blank `floors_above_ground`, the tallest height within `search_radius_m` is divided by `storey_height_m`
(ASSUMPTION), with a minimum of 1 and a maximum of `max_floors`. Points below `min_building_height_m` are flagged as
"no building detected". The user accepts each proposal. Accepted rows record the source in `ai_field_provenance` and pass
normal validation. Housing class is never inferred. Storey counts change loss through `storey_exposure`.

## 5. Schedule quality reviewer

Fixed checks run on raw uploaded rows:

| Check | Proposed fix |
|---|---|
| Duplicate IDs | rename |
| Swapped coordinates | swap |
| Outside the hazard maps | none |
| The same building listed twice | drop |
| Insured value about 10× area × cost (`tiv_ratio_band`) | set the value to area × cost |
| Value far below area × cost (`units_factor`) | ×1,000 or ×1,000,000 |
| Cost per m² outside ×/÷ `cost_ratio_factor` of the class median (starter portfolio, SYNTHETIC) | set to the median |
| Zero value | none |

Nothing changes until the user ticks a fix. Fixed rows carry a `review_note` and pass the same validation as any upload.
The AI only explains each kind of flag and suggests a question for the broker. Its schema has no field for a value, and
its figures are checked.

## 6. Ask the results

A question box on Overview and Loss curve. Answers come only from the briefing fact pack plus method facts: what a return
period is, why tier names do not match frequency, and that the score is not a depth. The AI must cite fact labels.
Invented labels are dropped, an answer with no cited facts is marked "not answerable", figures missing from the facts are
flagged, and each answer links to the relevant chart. Contact details are removed from the question. The audit log records
the model and counts, never the text.

## 7. Referral and quote memo

The memo drafts a referral to the head of underwriting, or a quote letter to the broker, from the decision fact pack
(`ai/decision.build_facts`). The schema has no outcome, share or price field. Figures are checked, and the underwriter
edits the draft before downloading it (Markdown or Word). Recording the decision still goes through
`platform/data.record_decision`, which recomputes the recommendation on the server.

## 8. Public risk notes

The note covers ground within `public_notes.radius_m` of a named flood area, sampled every `spacing_m`. It gives the share
of points flagged in each scenario (PROXY), whether the county lists the area (REAL), and what the map cannot see. **No
money, properties or client data** are used. The AI writes English and Kiswahili from the same facts, and the numbers in
each language are checked separately. A note stays a **draft** until a named Kiswahili reader confirms it, and a note with
unchecked figures cannot be confirmed.

## Choosing the AI model (Gemini or a local Llama model)

`ai/llm.choose` picks the model for each request:

1. **The organisation's limits.** The allowed models (`ai_providers`) and the default are set on
   **Organisation settings → AI models**. This is a security setting, so changing it needs a recent password check.
2. **Client data stays on the server, if required.** When `ai_local_for_client_data` is on, requests that carry client data
   use only the local model: documents, schedules, descriptions, schedule explanations, and the briefing, Ask and memos on
   runs with real exposure. If no local model is configured, the request is refused; it never falls back to the cloud.
3. **The member's preference.** Each member picks a model on **Profile & security → AI model**
   (`orgs.set_ai_preference`, audited). Without a preference, the organisation default applies, then the server default
   (`FLOODCAT_AI_PROVIDER`), then the first allowed model.

Public material (news articles, published flood reports, public notes) follows the member's choice. Place-name lookups use
the same model as the request they belong to. Every AI audit event records which provider answered.

## Tests

`tests/test_ai_enhancements.py` covers all eight with a fake LLM, a fake fetcher, in-memory layers and small temporary
GeoTIFFs. No test touches the network. `tests/test_ai_model_choice.py` covers the model-choice rules. `tests/test_ui_pages.py` renders the new pages for every role and runs Ask and the
drainage re-run through the interface.
