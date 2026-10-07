# Nairobi flood model — Day 1 results

Generated 2026-10-07 by `scripts/build_day1_outputs.py`. Config `nairobi-prototype-v0.5` (fingerprint `9e3ef0bca1cc`).

> **Every number here is illustrative.** The 600 properties are SYNTHETIC, the hazard is a PROXY, and the return periods,
> score-to-depth conversion and class adjustments are ASSUMPTIONS. Nothing is calibrated to Kenyan claims.

## Inputs

| File | Label | SHA-256 |
|---|---|---|
| `data/exposure_nairobi_with_hazard.csv` | SYNTHETIC exposure | `b60aa96590d5a2e7…` |
| `data/nairobi_pluvial_proxy_*.tif` (5) | PROXY hazard | read directly |
| `data/nairobi_hotspots_geocoded.csv` | REAL names, approximate points | `b597d843f80a800d…` |

## Headline (gross loss, no policy terms)

| Measure | Value | Plain English |
|---|---|---|
| Total insured value | KES 63,635,075,000 | 600 synthetic properties |
| 1-in-100 loss | KES 1,699,587,953 | 2.67% of value; a loss this size or larger has an assumed 1% chance each year |
| 1-in-250 loss | KES 2,649,188,965 | 4.16% of value; assumed 0.4% chance each year |
| Average annual loss | KES 125,887,686 | Long-run yearly average implied by the curve and the AAL assumptions |

## Loss by return period (EP curve)

| Tier | Return period | Annual chance | Loss | % of TIV |
|---|---|---|---|---|
| extreme | 1-in-10 | 10.0% | KES 263,818,827 | 0.41% |
| severe | 1-in-25 | 4.0% | KES 447,223,202 | 0.70% |
| moderate | 1-in-50 | 2.0% | KES 1,011,960,060 | 1.59% |
| occasional | 1-in-100 | 1.0% | KES 1,699,587,953 | 2.67% |
| common | 1-in-250 | 0.4% | KES 2,649,188,965 | 4.16% |

Tier names describe how extreme a cell is, not how often it floods: `extreme` keeps the top 5% of cells (narrowest
footprint, most frequent event); `common` keeps the top 40% (widest footprint, rarest event).

## EP curve from 10,000 simulated years

| Rarity | Loss | Simulation range (5–95th pct) | Modelled from |
|---|---|---|---|
| 1-in-2 | KES 2,951,230 | KES 0 – KES 7,189,959 | hazard tiers |
| 1-in-5 | KES 185,392,425 | KES 180,230,592 – KES 188,948,716 | hazard tiers |
| 1-in-10 | KES 293,048,956 | KES 284,519,625 – KES 297,892,158 | hazard tiers |
| 1-in-25 | KES 532,025,496 | KES 498,560,529 – KES 570,054,713 | hazard tiers |
| 1-in-50 | KES 1,005,840,302 | KES 871,383,949 – KES 1,081,430,346 | hazard tiers |
| 1-in-100 | KES 1,746,087,849 | KES 1,492,343,004 – KES 1,835,461,210 | hazard tiers |
| 1-in-200 | KES 2,241,206,718 | KES 2,067,636,478 – KES 2,449,499,891 | hazard tiers |
| 1-in-250 | KES 2,442,614,489 | KES 2,209,758,873 – KES 2,559,021,502 | hazard tiers |
| 1-in-500 | KES 3,157,651,032 | KES 2,621,943,879 – KES 3,466,051,000 | damage uncertainty only |
| 1-in-1,000 | KES 3,577,088,921 | KES 3,455,779,847 – KES 3,786,452,785 | damage uncertainty only |
| 1-in-2,000 | KES 3,786,476,845 | KES 3,639,571,948 – KES 4,139,503,518 | damage uncertainty only |
| 1-in-5,000 | KES 4,139,552,449 | KES 3,786,513,885 – KES 5,675,741,133 | damage uncertainty only |
| 1-in-10,000 | KES 4,384,288,294 | KES 3,834,750,773 – KES 5,675,741,133 | damage uncertainty only |

Average annual loss from the simulation: KES 124,746,748 (range KES 119,279,159 – KES 129,515,010);
4,963 of 10,000 years have no loss. Each simulated year draws its rarity and one damage-uncertainty
trial, and reads the loss between the five scenario points (linear in annual chance). Simulated from five assumed scenario points; beyond 1-in-250 only damage uncertainty varies, no rarer floods are modelled.

## Likely ranges per scenario (damage-ratio uncertainty, ASSUMPTION)

| Return period | 5th pct | Median | 95th pct |
|---|---|---|---|
| 1-in-10 | KES 148,272,070 | KES 248,084,049 | KES 406,593,050 |
| 1-in-25 | KES 255,521,055 | KES 421,276,618 | KES 678,940,211 |
| 1-in-50 | KES 596,802,758 | KES 959,229,082 | KES 1,533,697,121 |
| 1-in-100 | KES 1,008,308,109 | KES 1,609,409,816 | KES 2,586,854,072 |
| 1-in-250 | KES 1,577,877,880 | KES 2,504,508,614 | KES 4,039,798,385 |
| Average annual loss | KES 72,751,645 | KES 118,754,800 | KES 191,737,042 |

2,000 simulations; each property's damage ratio varies around its curve with log-spread σ=0.4, of which a
share ρ=0.5 is common to the whole portfolio. Damage-ratio uncertainty only; hazard, frequency and values are held fixed. Not a confidence interval on the true loss.

## Loss by housing class (1-in-100)

| Class | Properties | Insured value | Loss | Share of loss |
|---|---|---|---|---|
| concrete_rcc | 84 | KES 54,135,085,000 | KES 1,341,749,322 | 78.9% |
| permanent_masonry | 156 | KES 8,451,170,000 | KES 315,582,421 | 18.6% |
| semi_permanent | 181 | KES 850,710,000 | KES 31,177,282 | 1.8% |
| informal_iron_sheet | 179 | KES 198,110,000 | KES 11,078,928 | 0.7% |

## Accumulation near named hotspots (1-in-100)

Each property is tagged with its nearest named hotspot; it is grouped under that hotspot only within
2000 m (217 of 600 properties). Every property belongs to exactly one group.

| Area | Properties | Insured value | Loss | Share of loss |
|---|---|---|---|---|
| no named hotspot within radius | 383 | KES 36,844,755,000 | KES 952,672,056 | 56.1% |
| Mwiki | 15 | KES 2,452,310,000 | KES 292,608,999 | 17.2% |
| Kariobangi | 11 | KES 1,537,915,000 | KES 163,511,225 | 9.6% |
| Westlands | 7 | KES 663,500,000 | KES 77,701,560 | 4.6% |
| Dandora | 6 | KES 816,040,000 | KES 52,752,679 | 3.1% |
| Kitisuru | 14 | KES 2,824,290,000 | KES 52,039,521 | 3.1% |
| Nairobi West | 11 | KES 529,150,000 | KES 30,778,259 | 1.8% |
| Lang'ata | 16 | KES 3,581,705,000 | KES 22,489,663 | 1.3% |
| Parklands | 8 | KES 928,505,000 | KES 16,635,590 | 1.0% |
| Madaraka | 9 | KES 3,004,390,000 | KES 16,324,262 | 1.0% |

## Top 10 properties by loss (1-in-250)

| Property | Class | Insured value | Score | Assumed depth | Damage | Loss | Nearest hotspot |
|---|---|---|---|---|---|---|---|
| NBO-0316 | concrete_rcc | KES 522,650,000 | 0.627 | 0.94 m | 29.2% | KES 152,440,159 | Mwiki (3.9 km) |
| NBO-0130 | concrete_rcc | KES 958,965,000 | 0.292 | 0.44 m | 14.8% | KES 142,157,923 | Mwiki (4.6 km) |
| NBO-0416 | concrete_rcc | KES 1,356,500,000 | 0.189 | 0.28 m | 9.6% | KES 130,190,134 | Mwiki (6.1 km) |
| NBO-0468 | concrete_rcc | KES 914,905,000 | 0.270 | 0.40 m | 13.7% | KES 125,403,882 | Fedha (2.3 km) |
| NBO-0362 | concrete_rcc | KES 827,820,000 | 0.291 | 0.44 m | 14.8% | KES 122,408,286 | Mwiki (1.6 km) |
| NBO-0384 | concrete_rcc | KES 841,500,000 | 0.266 | 0.40 m | 13.5% | KES 113,754,657 | Kariobangi (1.0 km) |
| NBO-0452 | concrete_rcc | KES 380,470,000 | 0.610 | 0.91 m | 28.5% | KES 108,521,342 | Mwiki (1.1 km) |
| NBO-0572 | concrete_rcc | KES 831,600,000 | 0.248 | 0.37 m | 12.6% | KES 104,522,195 | Mwiki (2.3 km) |
| NBO-0466 | concrete_rcc | KES 526,250,000 | 0.352 | 0.53 m | 17.9% | KES 94,039,596 | Westlands (0.4 km) |
| NBO-0051 | concrete_rcc | KES 706,790,000 | 0.249 | 0.37 m | 12.7% | KES 89,527,345 | Kayole (3.5 km) |

## Hazard checks

- Raster lookup reproduces the attached scores for all 600 properties (largest difference 9.9e-17).
- Named hotspots flagged (score > 0): **12 of 24** in any tier; by tier
  extreme 1, severe 1, moderate 5, occasional 9, common 12. The misses are drainage-driven areas the proxy cannot see.
- 341 of 600 properties score zero in every tier and so carry
  no modelled loss. Zero means "not flagged by this proxy", not "cannot flood".

## Vulnerability

Base curve: Huizinga, de Moel & Szewczyk (2017), Global flood depth-damage functions, JRC105688, Table 3-1 (Africa, residential buildings, p.12); class depth scales and caps are Team A assumptions.

| JRC depth (m) | 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|---|---|
| Damage factor | 0.00 | 0.22 | 0.38 | 0.53 | 0.64 | 0.82 | 0.90 | 0.96 | 1.00 |

| Class | JRC depth scale | Damage cap | Meaning |
|---|---|---|---|
| informal_iron_sheet | 0.5 | 95% | reaches the JRC damage for depth d at 0.5·d |
| semi_permanent | 0.75 | 90% | reaches the JRC damage for depth d at 0.75·d |
| permanent_masonry | 1 | 85% | reaches the JRC damage for depth d at 1·d |
| concrete_rcc | 1.3 | 80% | reaches the JRC damage for depth d at 1.3·d |

Vulnerability matrix at max depth 1.5 m (damage ratio):

| Score | Assumed depth | informal_iron_sheet | semi_permanent | permanent_masonry | concrete_rcc |
|---|---|---|---|---|---|
| 0 | 0.00 m | 0.0% | 0.0% | 0.0% | 0.0% |
| 0.1 | 0.15 m | 13.2% | 8.8% | 6.6% | 5.1% |
| 0.2 | 0.30 m | 25.2% | 17.6% | 13.2% | 10.2% |
| 0.4 | 0.60 m | 44.0% | 31.6% | 25.2% | 20.3% |
| 0.6 | 0.90 m | 59.6% | 44.0% | 34.8% | 28.2% |
| 0.8 | 1.20 m | 71.2% | 55.2% | 44.0% | 35.5% |
| 1 | 1.50 m | 82.0% | 64.0% | 53.0% | 42.6% |

## Assumptions

| Assumption | Value | Label |
|---|---|---|
| Tier → return period | extreme 10 yr, severe 25 yr, moderate 50 yr, occasional 100 yr, common 250 yr | ASSUMPTION |
| Score → depth | depth = score × 1.5 m (pluvial base case) | ASSUMPTION |
| Class depth scales and caps | see Vulnerability | ASSUMPTION |
| AAL | trapezoid over annual chance; zero loss at 1-in-2; rarest loss held beyond 1-in-250 | ASSUMPTION |
| Insured value | supplied `tiv_kes` used as is (≈10× floor area × cost/m²; flagged on every row) | SYNTHETIC |
| Policy terms | none: gross loss = insured value × damage ratio | ASSUMPTION |

## Sensitivity (assumption scenarios, not confidence intervals)

| Case | 1-in-10 | 1-in-25 | 1-in-50 | 1-in-100 | 1-in-250 | AAL |
|---|---|---|---|---|---|---|
| base | KES 263,818,827 | KES 447,223,202 | KES 1,011,960,060 | KES 1,699,587,953 | KES 2,649,188,965 | KES 125,887,686 |
| area_times_cost_tiv | KES 26,381,746 | KES 44,722,148 | KES 101,195,802 | KES 169,958,660 | KES 264,918,745 | KES 12,588,725 |
| max_depth_1m | KES 179,112,942 | KES 305,515,565 | KES 688,878,280 | KES 1,151,980,499 | KES 1,791,003,169 | KES 85,502,640 |
| max_depth_1.5m | KES 263,818,827 | KES 447,223,202 | KES 1,011,960,060 | KES 1,699,587,953 | KES 2,649,188,965 | KES 125,887,686 |
| max_depth_2m | KES 335,873,714 | KES 572,104,910 | KES 1,322,440,732 | KES 2,232,475,447 | KES 3,484,586,268 | KES 162,223,669 |
| max_depth_4m | KES 587,249,040 | KES 1,040,049,783 | KES 2,458,989,985 | KES 4,106,827,051 | KES 6,358,978,417 | KES 290,921,586 |
| doubled_return_periods | KES 263,818,827 | KES 447,223,202 | KES 1,011,960,060 | KES 1,699,587,953 | KES 2,649,188,965 | KES 95,921,196 |

## Limitations

- Scenario EP points and AAL use assumed return periods, not a calibrated annual loss distribution.
- Losses are gross of policy terms; no deductible, limit or reinsurance is applied.
- Depth = score × max_depth_m is an assumption; the score is relative susceptibility, not measured depth.
- The JRC Africa residential curve rests on South African and Mozambican functions only; class scales and caps are assumptions.
- A zero score means the proxy did not flag the location, not that it cannot flood (drainage-driven flooding is invisible to it).

## Files

`nairobi_hazard_lookup.csv`, `nairobi_hotspot_check.csv`, `nairobi_vulnerability_matrix.csv`, `nairobi_property_losses.csv`,
`nairobi_ep_curve.csv`, `nairobi_accumulation.csv`, `nairobi_sensitivity.csv`, `nairobi_uncertainty_ranges.csv`, `nairobi_ylt_ep_curve.csv`.
