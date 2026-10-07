# Nairobi flood CAT implementation backlog

Tasks 1–45 target the hackathon prototype. Tasks 46–53 are the next product phase. The ordering is the intended implementation sequence; completed tasks should be checked against the acceptance notes in the project documentation.

## Day 1 — Baseline model and spatial persistence

1. Set up a reproducible Python environment with `uv` and install project dependencies.
2. Update README commands and tests that refer to removed `data/demo` and `data/raw` folders.
3. Run the existing test suite and record starting failures.
4. Inventory the eight supplied datasets and record SHA-256 hashes.
5. Confirm exposure rows, hotspots, raster tiers, and coordinate systems.
6. Reconcile the conflicting TIV totals and document the approximate 10× relationship.
7. Validate IDs, coordinates, construction classes, TIV, duplicates, and missing fields.
8. Verify prepared hazard scores against raster samples.
9. Confirm the baseline detection count on 24 geocoded hotspots.
10. Run the complete baseline CAT pipeline on the supplied portfolio.
11. Reconcile property losses to scenario portfolio totals.
12. Review and label illustrative score-to-damage vulnerability assumptions.
13. Document the assumed return-period mapping and scenario EP points.
14. Add sensitivity runs for TIV interpretation, vulnerability, and return-period assumptions.
15. Add PostgreSQL/PostGIS to Docker Compose.
16. Create versioned migrations for portfolios, assets, hotspots, evidence, and analysis runs.
17. Add spatial indexes and immutable model/run snapshots.
18. Replace the SQLite repository behind the API while keeping financial calculations independent.
19. Add database-backed import for supplied exposure and hotspot files.

## Day 2 — Evidence-driven AI

20. Define a structured evidence schema with source, excerpt, location, optional date, mechanism, and review status.
21. Connect one pretrained LLM through a replaceable extraction interface.
22. Require structured extraction and validate it against source text.
23. Reject invented quotations and accept genuinely unknown dates or locations.
24. Ingest a small curated set of sourced flood reports.
25. Detect duplicate reports of the same event.
26. Obtain a sourced list of all 37 named hotspots and identify the 13 absent from the supplied CSV.
27. Implement cached, rate-limited geocoding with multiple candidates retained.
28. Review ambiguous matches and label neighbourhood centres as approximate.
29. Separate approved evidence from unreviewed candidates.
30. Implement a documented spatial evidence signal.
31. Add an evidence-adjusted hazard provider independent of the optional classifier.
32. Preserve scenario ordering, coverage checks, and missing-versus-zero semantics.
33. Recalculate baseline and adjusted losses with the same exposure and financial assumptions.
34. Trace each changed property to its approved evidence and adjustment.

## Day 3 — Evaluation and underwriter presentation

35. Hold out geographically distinct hotspots and reports from enhancement inputs.
36. Measure extraction quality on hand-reviewed passages.
37. Compare baseline and adjusted detection on held-out hotspots, including unresolved and uncovered points.
38. Vary adjustment radius and strength as assumption sensitivity, without claiming statistical accuracy.
39. Add an underwriter view for portfolio checks, maps, property trace, breakdowns, accumulation, and scenario EP points.
40. Display baseline and adjusted results side by side with supporting evidence.
41. Export a report with provenance, assumptions, validation, losses, and limitations.
42. Test invalid, duplicate, incomplete, and outside-coverage exposure records.
43. Test that unapproved evidence has no effect and that prior runs remain reproducible.
44. Run tests, migrations, and an end-to-end demo on the supplied data.
45. Present one trace from source report through hazard adjustment to portfolio decision.

## After the hackathon

46. Obtain independent flood observations and suitable non-flood comparisons.
47. Calibrate and validate hazard adjustments.
48. Research locally appropriate vulnerability relationships using real depth and loss observations.
49. Add policy terms, deductibles, limits, and reinsurance layers.
50. Add tenant isolation, roles, audit history, backups, and stronger API security.
51. Add managed geocoding, background jobs, and monitoring for larger portfolios.
52. Evaluate supervised ML, RAG infrastructure, and agent orchestration against measured needs.
53. Pilot with licensed data and compare estimates with observed outcomes.
