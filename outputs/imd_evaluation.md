# Infrastructure & Maintenance Deficit index — evaluation

Generated 2026-10-08 by `scripts/evaluate_imd.py`. Inputs: `outputs/imd_index.tif` (612,126 OpenStreetMap buildings, https://download.geofabrik.de/africa/kenya-261006.osm.pbf), the five terrain proxy maps and the 24 named hotspots. The index is an evaluation layer: it is not applied to losses.

**Labels.** Index = PROXY (OSM footprints; drains and maintenance are not observed). Thresholds, weights and the score uplift = ASSUMPTION, fixed before this check was first run. Hotspot names = REAL, coordinates approximate.

## Named flood areas (24)

- Terrain proxy alone flags **12 of 24**.
- With the index: **21 of 24**.
- Newly flagged: Donholm, Fedha, Madaraka, Lang'ata, Kawangware, Kangemi, Parklands, Kileleshwa, Kibera.
- Still missed: Lavington, Westlands, Kitisuru.
- Of the newly flagged, marginal (index below 0.05): Madaraka, Lang'ata, Kileleshwa.
- Rule: flagged when the score is above zero in any tier at the geocoded point.

| Area | Roofed share | Buildings/ha | Index | Terrain flags it | With index |
|---|---:|---:|---:|---|---|
| Kayole | 55% | 78 | 0.77 | yes | yes |
| Dandora | 42% | 54 | 0.59 | yes | yes |
| Kibera | 41% | 50 | 0.56 | no | yes |
| Kangemi | 41% | 39 | 0.50 | no | yes |
| Tassia | 38% | 15 | 0.39 | yes | yes |
| Mwiki | 36% | 29 | 0.38 | yes | yes |
| Kawangware | 37% | 27 | 0.37 | no | yes |
| Komarock | 31% | 40 | 0.34 | yes | yes |
| Fedha | 31% | 14 | 0.26 | no | yes |
| Ruai | 26% | 28 | 0.20 | yes | yes |
| Parklands | 25% | 8 | 0.17 | no | yes |
| Donholm | 24% | 20 | 0.16 | no | yes |
| Nairobi West | 23% | 18 | 0.14 | yes | yes |
| Kariobangi | 22% | 25 | 0.12 | yes | yes |
| Chiromo | 17% | 7 | 0.04 | yes | yes |
| Kileleshwa | 16% | 9 | 0.01 | no | yes |
| Madaraka | 15% | 4 | 0.00 | no | yes |
| Lang'ata | 15% | 7 | 0.00 | no | yes |
| Kiambiu | 10% | 5 | 0.00 | yes | yes |
| Njiru | 8% | 14 | 0.00 | yes | yes |
| Lavington | 14% | 8 | 0.00 | no | no |
| Westlands | 10% | 4 | 0.00 | no | no |
| Kitisuru | 8% | 4 | 0.00 | no | no |
| Mathare | 9% | 7 | 0.00 | yes | yes |

## How much of the map it flags

A hit rate means little if the whole city is flagged. Share of hazard-map cells with a score above zero (any tier):

- Terrain only: 40.0%
- With the index: 44.8% (index above zero on 10.4% of cells)

## Better than chance?

Every named area is built-up (at least 2 buildings/ha in the window). Within built-up ground the index is above zero on 36% of cells (29% at 0.05 or more). An index switched on at random over built-up ground would therefore be expected to find about 4.3 of the 12 terrain misses (3.5 non-marginal); it finds 9 (6 non-marginal). With 12 places this is weak evidence, not proof.

## Read with care

- A higher hit rate is not evidence of a better model. The 24 hotspots are the only check, and 24 points cannot
  separate a good index from a lucky one.
- The index measures runoff pressure (roofed, crowded ground), not drainage condition. Low-density areas that flood
  because drains are blocked or rivers back up will stay missed.
- OpenStreetMap completeness varies: a well-mapped informal settlement reads as dense, an unmapped one as empty.
  Mathare and Kiambiu are among the densest settlements in Nairobi yet read as sparse here (check mapping and the
  hotspot coordinates before relying on the index there).
- Roads, car parks and paved yards are not counted, so imperviousness is understated, most in commercial areas.

Map data © OpenStreetMap contributors, ODbL 1.0.
