# Next implementation tasks

1. Add the actual prepared CSV, raw exposure CSV, rasters and geocoded hotspots. Verify row counts, aggregate TIV, raster coverage and prepared-vs-resampled scores. Never replace missing hazard with zero.
2. Research JRC/Huizinga or regional vulnerability relationships. Digitize/source knots, document construction adjustments and sensitivity ranges. Replace illustrative config before presenting a sourced model.
3. Independently collect drainage/impervious signals and review flood evidence, including source dates and confidence. Approximate neighbourhood coordinates are not exact flooded buildings.
4. Establish honest train/test geographic groups and label provenance. Supplied positive hotspots cannot support negative-label metrics alone; avoid using evaluation locations or their reports to train/engineer the model.
5. Train and assess the ML artifact. Run the same portfolio, vulnerability and financial assumptions through both hazard providers. Export hazard/damage/loss changes, held-out metrics, and uncovered observations.
6. Assess parameter sensitivity (damage curves, RP mapping, uplift strength, drainage signal, evidence radius). These are not calibrated observational uncertainties; keep assumption scenarios separate from confidence intervals.
7. Build the frontend against OpenAPI: upload/review → exposure map → baseline/enhanced map → vulnerability/property trace → portfolio EP/construction/grid accumulation → provenance/export.
8. Commercial pilot: arrange independent validation and licensed inputs, add user/tenant access and durable jobs. Commercial positioning should be explainable localized portfolio intelligence; do not claim calibrated pricing accuracy or guaranteed losses.

## Extension boundaries

Hazard providers expose `scores(asset)`; replace/extend them for new data without changing financial code. Core calculations do not import FastAPI or SQLite. ML inference uses portable JSON coefficients. Add feature providers or a geocoding provider behind explicit service interfaces, not in financial helpers. SQLite stores immutable result snapshots and a reviewable evidence registry; an enterprise deployment needs migrations, authentication roles and approval/revocation history.

## Scope intentionally deferred

Frontend, real portfolio integration, policy financial terms, treaty layers, multi-peril aggregation, stochastic AAL, hydrodynamic modelling and automatic geocoding are outside this scaffold's demonstrated scope. They should not be reported as implemented features.
