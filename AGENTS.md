# Backend conventions

Keep financial and hazard calculations independent of API/storage code. Put shared factors in ModelConfig, not scattered literals. Preserve synthetic/proxy/assumed provenance in every result. Never fill missing hazard or outside coverage with zero. Do not reorder losses to conceal invalid scenario ordering. Require explicit partial-analysis selection when rejecting records.

Use Decimal for currency and expose decimal strings to API clients. Store a full configuration/evidence snapshot for reproducibility. Do not report AI improvement without independent held-out evidence. Do not use evaluation hotspots or their evidence as training labels/features. Default curves are illustrative, not published JRC parameters.

Run `python -m pytest -q` from this directory after model changes. New ML or geospatial dependencies belong in optional extras. Actual starter data goes in data/raw and is not included in the source archive. Do not add real client data or credentials to the repository.

No frontend or public deployment is part of this backend task.
