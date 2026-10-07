"""Read-only checks of the supplied Nairobi starter files."""

from collections import Counter
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from ..core.constants import TIERS
from ..exposure.loaders import read_csv
from ..exposure.validation import parse_row, validate_rows
from ..hazard.interpretation import validate_scores
from ..hazard.raster import RasterHazard


def audit_data(directory):
    import csv
    import rasterio

    root = Path(directory)
    names = ["exposure_nairobi_synthetic.csv", "exposure_nairobi_with_hazard.csv",
             "nairobi_hotspots_geocoded.csv"]
    names += [f"nairobi_pluvial_proxy_{tier}.tif" for tier in TIERS]
    files = {name: {"bytes": (root / name).stat().st_size,
                    "sha256": sha256((root / name).read_bytes()).hexdigest()} for name in names}
    plain = read_csv(root / names[0])
    prepared = read_csv(root / names[1])
    assets, issues = validate_rows(prepared)
    tier_values = {tier: [float(row[f"hazard_score_{tier}"]) for row in prepared]
                   for tier in TIERS}
    ordered_score_count = sum(
        1 for row in prepared
        if validate_scores({tier: float(row[f"hazard_score_{tier}"]) for tier in TIERS})
    )
    base_columns = set(plain[0])
    base_equal = len(plain) == len(prepared) and all(
        {key: row[key] for key in base_columns} == base
        for base, row in zip(plain, prepared)
    )
    with (root / names[2]).open(newline="", encoding="utf-8-sig") as stream:
        hotspots = list(csv.DictReader(stream))

    raster_info = {}
    for tier in TIERS:
        with rasterio.open(root / f"nairobi_pluvial_proxy_{tier}.tif") as ds:
            raster_info[tier] = {"width": ds.width, "height": ds.height,
                                 "bands": ds.count, "crs": str(ds.crs),
                                 "bounds": list(ds.bounds),
                                 "pixel_size_degrees": list(ds.res),
                                 "nodata": ds.nodata}

    maximum_difference = 0.0
    mismatches = 0
    uncovered = 0
    with RasterHazard(root) as hazard:
        for row in prepared:
            asset = parse_row(row)
            sampled = hazard.scores(asset)
            if any(value is None for value in sampled.values()):
                uncovered += 1
                continue
            for tier in TIERS:
                diff = abs(sampled[tier] - float(row[f"hazard_score_{tier}"]))
                maximum_difference = max(maximum_difference, diff)
                mismatches += diff > 1e-7
        from types import SimpleNamespace
        hotspot_scores = [hazard.scores(SimpleNamespace(
            lat=float(row["lat"]), lon=float(row["lon"]))) for row in hotspots]

    tiv = sum((asset.tiv_kes for asset in assets), Decimal(0))
    replacement = sum((Decimal(str(asset.floor_area_m2)) * Decimal(str(asset.cost_per_m2_kes))
                       for asset in assets if asset.floor_area_m2 and asset.cost_per_m2_kes), Decimal(0))
    return {
        "files": files, "total_bytes": sum(item["bytes"] for item in files.values()),
        "exposure_count": len(prepared), "unique_ids": len({row["loc_id"] for row in prepared}),
        "base_fields_match_prepared": base_equal, "hotspot_count": len(hotspots),
        "housing_classes": dict(Counter(asset.housing_class for asset in assets)),
        "validation_issue_counts": dict(Counter(issue["code"] for issue in issues)),
        "validation_error_count": sum(issue["severity"] == "error" for issue in issues),
        "score_interpretation": "relative susceptibility index, unitless; not flood depth or annual probability",
        "score_ordered_count": ordered_score_count,
        "tier_score_summary": {
            tier: {"minimum": min(values), "maximum": max(values),
                   "positive_properties": sum(value > 0 for value in values)}
            for tier, values in tier_values.items()
        },
        "tiv_kes": str(tiv), "area_times_cost_kes": str(replacement),
        "tiv_to_area_cost_ratio": str(tiv / replacement) if replacement else None,
        "raster_info": raster_info,
        "prepared_score_mismatches": mismatches,
        "prepared_score_max_absolute_difference": maximum_difference,
        "exposure_points_outside_raster": uncovered,
        "baseline_common_hotspots_positive": sum(
            score["common"] is not None and score["common"] > 0 for score in hotspot_scores),
        "baseline_hotspots_outside_raster": sum(score["common"] is None for score in hotspot_scores),
        "provenance": {"exposure": "synthetic", "hazard": "derived susceptibility proxy",
                       "hotspots": "named areas with approximate geocodes"},
    }
