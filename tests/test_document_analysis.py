"""Submission documents read as a whole: data points, relevance, cross-reference, flood history, implied metrics."""

from floodcat.ai.document_analysis import analyse, implied_metrics, term_value
from floodcat.core.config import load_config

SLIP = """DANDORA TEST LTD - INDUSTRIAL ALL RISK
Sum Insured - 100% KES 404,072,713.00
Premium - 100%: KES 1,743,210.00
Our Fac/RE Share: 90.00%
Our Fac/RE Sum Insured: KES 363,665,441.70
Total Deductions: 32.50%
Accepted Share: 7.5000%
Accepted Sum Insured: KES 30,305,453.48
Accepted Premium: KES 130,740.75
2. Bush Fire
Loss by the burning of forests is covered.
10. Removal of Debris
Costs not exceeding 5% of the sum insured.
FLOOD HISTORY
In April 2018 storm drains overflowed and the yard flooded to 0.4 m; the claim paid was KES 2,500,000.
In May 2024 water from the blocked culvert entered the stores to 0.6 m, loss KES 6,000,000."""

RESPONSE = {
    "placement_terms": [
        {"term": "sum_insured_100", "value_number": 404072713.0, "value_text": "", "quote": "Sum Insured - 100% KES 404,072,713.00"},
        {"term": "premium_100", "value_number": 1743210, "value_text": "", "quote": "Premium - 100%: KES 1,743,210.00"},
        {"term": "placed_share_pct", "value_number": 90, "value_text": "", "quote": "Our Fac/RE Share: 90.00%"},
        {"term": "placed_sum_insured", "value_number": 363665441.70, "value_text": "", "quote": "Our Fac/RE Sum Insured: KES 363,665,441.70"},
        {"term": "deductions_pct", "value_number": 32.5, "value_text": "", "quote": "Total Deductions: 32.50%"},
        {"term": "accepted_share_pct", "value_number": 7.5, "value_text": "", "quote": "Accepted Share: 7.5000%"},
        {"term": "accepted_sum_insured", "value_number": 30305453.48, "value_text": "", "quote": "Accepted Sum Insured: KES 30,305,453.48"},
        {"term": "accepted_premium", "value_number": 999999, "value_text": "", "quote": "Accepted Premium: KES 130,740.75"},  # wrong number
        {"term": "debris_removal_pct", "value_number": 5, "value_text": "", "quote": "Costs not exceeding 5% of the sum insured."},
        {"term": "broker", "value_number": None, "value_text": "Invented Brokers", "quote": "Placed by Invented Brokers"},  # not in text
    ],
    "sections": [
        {"heading": "2. Bush Fire", "topic": "other_peril", "flood_relevant": False, "reason": "fire only"},
        {"heading": "10. Removal of Debris", "topic": "flood_cover_extension", "flood_relevant": True, "reason": "adds to a loss"},
        {"heading": "FLOOD HISTORY", "topic": "flood_history", "flood_relevant": True, "reason": "past floods"},
    ],
    "flood_history": [
        {"date_text": "May 2024", "year": 2024, "place": "stores", "description": "blocked culvert", "depth_m": 0.6,
         "loss_kes": 6000000, "cause": "drainage", "quote": "In May 2024 water from the blocked culvert entered the stores to 0.6 m"},
        {"date_text": "April 2018", "year": 2018, "place": "yard", "description": "drains overflowed", "depth_m": 0.4,
         "loss_kes": 2500000, "cause": "drainage", "quote": "In April 2018 storm drains overflowed"},
        {"date_text": "2010", "year": 2010, "place": "x", "description": "invented", "depth_m": 2, "loss_kes": 1,
         "cause": "river", "quote": "The river flooded in 2010"},  # not in the text
    ],
    "properties": [{"occupancy_text": "Industrial Manufacturing Facility"}],
}

PROPERTY = {
    "name": "Dandora Test",
    "row": {"housing_class": "concrete_rcc", "tiv_kes": 404072713.0, "gross_floor_area_m2": None},
    "fields": {"construction": {"value": "Reinforced Concrete"}},
    "hazard": [{"source": "stated coordinates", "lat": -1.2576, "lon": 36.8962,
                "scores": {"extreme": 0.13, "severe": 0.25, "moderate": 0.35, "occasional": 0.41, "common": 0.46},
                "nearest_hotspot": {"nearest_hotspot": "Kariobangi", "hotspot_distance_m": 1600.0, "within_hotspot_radius": True}}],
    "checks": [],
    "flood_claims": [],
}


def result():
    return analyse(SLIP, RESPONSE, [PROPERTY], load_config())


def test_data_points_are_kept_only_with_a_matching_quote_and_number():
    pts = result()["data_points"]
    kept = {t["term"] for t in pts["terms"]}
    assert {"sum_insured_100", "premium_100", "placed_share_pct", "accepted_share_pct", "debris_removal_pct"} <= kept
    assert "accepted_premium" not in kept and "broker" not in kept  # wrong number; quote not in the document
    assert len(pts["unverified"]) == 2
    assert "Flood deductible" in pts["missing"]
    assert term_value(pts, "premium_100") == 1743210


def test_relevant_and_irrelevant_sections_are_separated_with_reasons():
    rel = result()["relevance"]
    assert [x["heading"] for x in rel["relevant"]] == ["10. Removal of Debris", "FLOOD HISTORY"]
    assert rel["irrelevant"][0]["topic"] == "Another peril" and rel["irrelevant"][0]["found"]


def test_building_is_cross_referenced_with_curve_hazard_and_named_areas():
    rows = {r["indicator"]: r for r in result()["cross_reference"][0]["rows"]}
    assert "÷ 1.3" in rows["Construction → damage curve"]["model"]
    assert "non-residential" in rows["Occupancy → curve type"]["flag"]
    assert "common 0.46" in rows["Location → hazard map"]["model"]
    assert "Kariobangi" in rows["Location → named flood areas"]["model"]


def test_flood_history_is_ordered_summarised_and_unquoted_events_dropped():
    hist = result()["flood_history"]
    assert [e["year"] for e in hist["events"]] == [2018, 2024]
    assert "2 flood events between 2018 and 2024" in hist["summary"]
    assert "KES 8,500,000" in hist["summary"] and "drainage ×2" in hist["summary"] and "0.6 m" in hist["summary"]


def test_no_flood_history_says_so_and_lists_what_to_ask():
    hist = analyse(SLIP, {**RESPONSE, "flood_history": []}, [PROPERTY], load_config())["flood_history"]
    assert hist["events"] == [] and "no flood history" in hist["summary"] and hist["ask_for"]


def test_implied_metrics_and_arithmetic_checks():
    implied = result()["implied"]
    m = {x["metric"]: x["value"] for x in implied["metrics"]}
    assert m["Premium rate"] == "0.431%" and m["Rate per mille"] == "4.31 ‰"
    assert m["Premium after deductions"] == "KES 1,176,666.75"
    assert m["Debris removal could add"] == "up to KES 20,203,636"
    checks = {c["check"].split(" = ")[1]: c["ok"] for c in implied["checks"]}
    assert checks == {"placed sum insured": True, "accepted sum insured": True}


def test_modelled_metrics_appear_once_the_model_has_run(starter_rows):
    from floodcat.services.analysis import analyse as run_model

    report = run_model(starter_rows[:5], load_config())
    implied = implied_metrics(result()["data_points"], report)
    names = [x["metric"] for x in implied["metrics"]]
    assert "Modelled annual loss (gross loss)" in names and "Modelled loss ratio" in names
    assert "Accepting reinsurer's modelled annual loss" in names


def test_documents_without_the_new_fields_still_work():
    out = analyse("text", {"properties": []}, [], load_config())
    assert out["data_points"]["count"] == 0 and out["relevance"]["share_relevant"] is None
    assert out["flood_history"]["events"] == []
