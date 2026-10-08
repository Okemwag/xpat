"""Warning for properties near a named flood area that the map scores low: shown, never a loss input."""

from floodcat.core.constants import TIERS
from floodcat.hazard.hotspots import Hotspot, drainage_hints, hint_text, load_hotspots
from floodcat.services.analysis import analyse
from conftest import DATA, row

HOTSPOTS = (Hotspot("Testville", -1.2800, 36.8200),)


def site(loc_id, lat, common):
    return row(loc_id, lat=str(lat), lon="36.8200", scores=(0, 0, 0, 0, common))


def test_hint_needs_both_closeness_and_a_low_score(config):
    rows = [site("NEAR-LOW", -1.2850, 0.04),   # ~0.55 km, low score -> hint
            site("NEAR-HIGH", -1.2850, 0.40),  # close but the map flags it -> no hint
            site("FAR-LOW", -1.3100, 0.04)]    # ~3.3 km away -> no hint
    report = analyse(rows, config, hotspots=HOTSPOTS)
    hinted = [h["loc_id"] for h in report["drainage_hints"]["properties"]]
    assert hinted == ["NEAR-LOW"]
    h = report["drainage_hints"]["properties"][0]
    assert h["nearest_hotspot"] == "Testville" and 500 < h["distance_m"] < 600
    assert "consider drainage evidence" in hint_text(h, config) and "loss is unchanged" in hint_text(h, config)


def test_hint_never_changes_a_loss(starter_rows, config):
    hotspots = load_hotspots(DATA / "nairobi_hotspots_geocoded.csv")
    strict = analyse(starter_rows, config, hotspots=hotspots)
    loose = analyse(starter_rows, config.replace(drainage_hint={**config.drainage_hint, "radius_m": 5000.0,
                                                                 "max_rarest_score": 0.9}), hotspots=hotspots)
    assert len(loose["drainage_hints"]["properties"]) > len(strict["drainage_hints"]["properties"]) > 0
    for t in TIERS:
        assert [r["loss_kes"] for r in strict["runs"]["baseline"]["property_losses"][t]] == \
               [r["loss_kes"] for r in loose["runs"]["baseline"]["property_losses"][t]]
    assert strict["runs"]["baseline"]["aal"] == loose["runs"]["baseline"]["aal"]


def test_no_hotspots_means_no_hints(starter_rows, config):
    assert analyse(starter_rows[:5], config)["drainage_hints"] is None


def test_rarest_tier_rows_drive_the_rule(config):
    rows = [{"loc_id": "A", "nearest_hotspot": "X", "hotspot_distance_m": 999.0, "hazard_score": 0.099},
            {"loc_id": "B", "nearest_hotspot": "X", "hotspot_distance_m": 1001.0, "hazard_score": 0.0},
            {"loc_id": "C", "nearest_hotspot": "X", "hotspot_distance_m": 10.0, "hazard_score": 0.1}]
    assert [h["loc_id"] for h in drainage_hints(rows, config)["properties"]] == ["A"]


def test_document_review_warns_for_a_site_near_chiromo(config):
    """The edited memo's site: 0.85 km from Chiromo with a rarest-tier score of about 0.04."""
    import pytest

    pytest.importorskip("rasterio")
    from floodcat.ai.submission import assess_property
    from floodcat.hazard.raster import RasterHazard

    hazard = RasterHazard(DATA).load()
    hotspots = load_hotspots(DATA / "nairobi_hotspots_geocoded.csv")
    prop = {"name": "Greg Industrial", "housing_class": "concrete_rcc", "construction_quote": "Reinforced Concrete",
            "tiv_kes": 404072713, "tiv_quote": "KES 404,072,713.00", "coordinates_text": "-1.26667, 36.8",
            "coordinates_quote": "-1.26667, 36.8", "locality": ""}
    text = "Reinforced Concrete KES 404,072,713.00 Geographic Coordinates: -1.26667, 36.8"
    assessed = assess_property(prop, text, None, hazard, hotspots, config, None)
    codes = {c["code"]: c["message"] for c in assessed["checks"]}
    assert "near_named_area_low_score" in codes and "Chiromo" in codes["near_named_area_low_score"]


def test_report_lists_hinted_properties(starter_rows, config):
    from floodcat.reporting.document import Table, build_document

    report = analyse(starter_rows, config, hotspots=load_hotspots(DATA / "nairobi_hotspots_geocoded.csv"))
    doc = build_document(report, label="Test")
    table = next(b for b in doc.blocks if isinstance(b, Table) and b.sheet == "Drainage hints")
    assert len(table.rows) == len(report["drainage_hints"]["properties"])
