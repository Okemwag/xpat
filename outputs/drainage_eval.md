# Drainage-passage classifier — evaluation

Generated 2026-10-08 by `scripts/evaluate_drainage.py`. Model `BAAI/bge-small-en-v1.5` (local). Thresholds (set on dev only): drainage similarity ≥ 0.6, margin over the best contrast ≥ 0.035.

Passages are hand-written in the style of news and humanitarian reports (SYNTHETIC). This checks that the scoring separates drainage failure from river overflow and from flood news without a cause; it is not accuracy on real reports.

| Split | Passages | Drainage passages | Precision | Recall | River passages wrongly flagged |
|---|---:|---:|---:|---:|---:|
| dev | 28 | 12 | 90% | 75% | 0 |
| test (held out) | 28 | 12 | 100% | 83% | 0 |

## Held-out errors

- missed drainage (similarity 0.58, margin +0.053): Blocked drains turned the bus stage into a lake, and passengers waded through waist-deep water to reach the matatus.
- missed drainage (similarity 0.64, margin -0.010): Every rainy season the estate floods because the outfall drain is choked with waste from the nearby market.
