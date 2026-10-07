# AI ingestion accuracy

Generated 2026-10-07 by `scripts/evaluate_ingestion.py` · prompt `ingest-v1` · cases `ingestion-cases-v1` ·
models used: gemini-3.5-flash (8), gemini-3.8-flash (4).

> 12 held-out, team-written SYNTHETIC descriptions (`evaluation/ingestion_cases.json`), never shown to the model
> as examples. A small check of extraction, not a statistical accuracy estimate.

| Measure | Result |
|---|---|
| Cases fully correct | 12/12 |
| Groups found | 15/15 (100%) |
| Housing class (incl. correctly flagged as unknown) | 15/15 (100%) |
| Building count | 15/15 (100%) |
| Value per building (within 2%) | 14/14 (100%) |
| Place located | 15/15 (100%) |
| Quote found in the text | 15/15 (100%) |
| Spurious extra groups | 0 |
| Total buildings exact | 12/12 |

| Case | Fully correct | Buildings (got/expected) | Fields wrong |
|---|---|---|---|
| simple-each | yes | 20/20 | — |
| two-groups | yes | 13/13 | — |
| group-total | yes | 8/8 | — |
| swahili-mabati | yes | 10/10 | — |
| no-value | yes | 5/5 | — |
| no-class | yes | 3/3 | — |
| area-and-rate | yes | 1/1 | — |
| word-numbers | yes | 12/12 | — |
| three-groups | yes | 36/36 | — |
| prompt-injection | yes | 6/6 | — |
| coordinates-given | yes | 1/1 | — |
| noise | yes | 15/15 | — |

Every AI record is still shown for human review before it is modelled; these figures describe the first draft.
