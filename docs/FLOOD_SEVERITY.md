# Nairobi flood severity: baseline interpretation

## Decision

The Nairobi baseline uses **Option 1** from the Team A guide: `data/exposure_nairobi_with_hazard.csv`. Its five hazard columns are already attached to the same 600 synthetic buildings in `exposure_nairobi_synthetic.csv`. The baseline therefore reads those columns directly. The five GeoTIFFs remain the source rasters for verification and for later work on new exposures or an improved hazard layer.

The prepared CSV is the **source** for the property-level baseline. The explicit deliverables are [the flood severity table with its explanation](../outputs/nairobi_flood_severity.md) and [the matching analysis CSV](../outputs/nairobi_flood_severity.csv). Both are generated directly from the prepared file by `scripts/build_flood_severity_output.py`, with no score transformation.

## What each hazard value means

Each `hazard_score_*` value is a **unitless, relative flood-susceptibility index on a 0–1 scale**:

- `0` means the supplied proxy does not flag susceptibility at that property in that tier. It does **not** mean flooding is impossible.
- A larger value means stronger susceptibility according to the supplied proxy. `1` is the top of the index's possible scale; it is **not** one metre, a 100% flood chance, or an observed maximum flood.
- The score is used as a continuous model input. We do not impose unsupported cutoffs such as “low”, “medium”, or “high” physical flood depth.

The guide describes the underlying Nairobi layers as a constructed proxy from terrain elevation, local depressions, and proximity to mapped rivers or streams. That combination misses some urban drainage-driven flooding. A score therefore expresses what this **particular proxy** detects, not complete real-world flood severity.

The baseline **does not convert scores to metres**. Assigning `1 = 4 m` would create assumed depths without a measured score-to-depth relationship. If a future model has credible local depth observations or a validated physical mapping, that conversion can be reconsidered and documented separately.

## The five columns

| Column | Buildings with a score above 0 | Highest score among the 600 buildings |
|---|---:|---:|
| `hazard_score_common` | 259 | 0.6855 |
| `hazard_score_occasional` | 174 | 0.6558 |
| `hazard_score_moderate` | 110 | 0.6198 |
| `hazard_score_severe` | 51 | 0.5629 |
| `hazard_score_extreme` | 32 | 0.4975 |

These are the supplied tier names. Their footprints become **narrower** from `common` to `extreme`; at every supplied building, scores stay the same or decrease in that direction. The names should not be interpreted as measured annual event frequencies or physical water-depth categories. The prototype assigns return periods separately, as explicit assumptions, to create comparable scenario loss points. The wider `common` layer is assigned the rarer, higher-loss scenario in that mapping, despite its name.

## Checks on the supplied dataset

The prepared CSV has **600 rows and 14 columns**: nine exposure fields plus these five hazard scores. All 600 location IDs are unique. None of the five score columns is missing a value, and every score falls within 0–1. All 600 rows obey the expected tier ordering. Independent sampling of the five supplied rasters reproduces every prepared score within numerical precision. All 600 properties lie inside raster coverage.

The common-tier proxy has a positive score at **12 of the 24** supplied, approximately geocoded flood hotspot points. That is a positive-location detection check, **not** an accuracy or false-positive-rate estimate. The other 13 areas in the wider list of 37 are not present in the supplied geocoded file.

The reproducible counts and file hashes are recorded in [DATA_AUDIT.json](DATA_AUDIT.json).

## Handoff to vulnerability and loss

For the baseline, the next stage uses the score **directly** as the input to a construction-specific, monotone score-to-damage function. It does not call that input a measured flood depth. A property's illustrative gross loss is its supplied insured value multiplied by the resulting damage ratio.

Those damage functions are currently assumptions and have not been calibrated to Kenyan claims or observed depths. In particular, the current function gives zero modelled damage at a score of zero; this reflects the chosen proxy and function, **not** proof that an unflagged building is safe. The supplied portfolio's insured values also have an unresolved roughly tenfold discrepancy with area times cost, described in [DATA_RECONCILIATION.md](DATA_RECONCILIATION.md).

**Baseline statement:** “We use the five supplied 0–1 Nairobi flood-susceptibility scores as relative hazard inputs at each synthetic property. We do not claim they are flood depths or annual flood probabilities. Loss estimates depend on an illustrative, construction-specific mapping from those scores to damage ratios and on explicitly assumed scenario frequencies.”
