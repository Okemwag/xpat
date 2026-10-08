# What the AI stages change — measured

Generated 2026-10-08 by `scripts/demo_ai_effect.py`. Every input below is SYNTHETIC.

## A. Free-text exposure ingestion

Held-out description (`three-groups`): “Portfolio: 30 mabati structures in Kiambiu (150k each); 4 stone houses in Donholm (3.5m each); 2 concrete apartment blocks in South B (80m each).”

Model gemini-3.5-flash (ingest-v1) produced 36 property rows:

| Place | Class | Buildings | Value each | Quote found in the text |
|---|---|---:|---:|---|
| Kiambiu | informal_iron_sheet | 30 | KES 150 k | yes |
| Donholm | permanent_masonry | 4 | KES 3.5 m | yes |
| South B | concrete_rcc | 2 | KES 80.0 m | yes |

Modelled: 36 properties, KES 178.5 m insured; 1-in-100 loss KES 927 k; 1-in-250 loss KES 1.3 m; AAL KES 22 k. No rows can be produced from the text without the AI stage, so there is no loss to compare.

1-in-250 loss by class: informal_iron_sheet KES 1.3 m; concrete_rcc KES 0 k; permanent_masonry KES 0 k

## B. Flood reports → drainage evidence → hazard → loss

Three demonstration reports read locally (BAAI/bge-small-en-v1.5); approval simulated. Places found:

| Place | Drainage-deficit factor | Reports |
|---|---:|---:|
| Githogoro | 0.96 | 1 |
| Marurui | 0.96 | 1 |
| Kaloleni | 0.88 | 2 |
| Kabiria | 0.70 | 1 |

Starter portfolio, with vs without this evidence: 21 properties had their hazard raised; average annual loss KES 125.9 m → KES 139.6 m (+KES 13.7 m).

| Return period | Without evidence | With evidence |
|---|---:|---:|
| 1-in-10 | KES 263.8 m | KES 296.5 m |
| 1-in-25 | KES 447.2 m | KES 512.5 m |
| 1-in-50 | KES 1.01 bn | KES 1.11 bn |
| 1-in-100 | KES 1.70 bn | KES 1.83 bn |
| 1-in-250 | KES 2.65 bn | KES 2.80 bn |

A higher loss is not evidence of a better model. In the product nothing changes until a named reviewer approves.
