# Nairobi flood severity data

For the baseline, use **`exposure_nairobi_with_hazard.csv`**. It contains the 600 synthetic buildings and their five attached 0–1 flood-susceptibility scores: `common`, `occasional`, `moderate`, `severe`, and `extreme`.

The scores are relative, unitless proxy values. They are **not flood depths in metres** or annual flood probabilities. A value of zero means this proxy did not flag that location; it does not rule out flooding.

`exposure_nairobi_synthetic.csv` contains the same buildings without attached scores. The five GeoTIFFs can reproduce the attached values or support later hazard work. `nairobi_hotspots_geocoded.csv` provides 24 approximate named locations for a limited baseline check; it is not an exposure portfolio.

See [the flood-severity interpretation](../docs/FLOOD_SEVERITY.md) for the chosen score meaning, tier ordering, validation, and handoff to the vulnerability stage.
