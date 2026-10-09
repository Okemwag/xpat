"""The correction switches (drainage model, approved evidence) build the right run settings, and a switched-on correction
changes the losses all the way to the financial engine."""

import sys
import pytest
from conftest import DATA

pytest.importorskip("streamlit")
sys.path.insert(0, str(DATA.parent / "app"))
from ui.corrections_view import active, with_corrections  # noqa: E402


def test_switching_on_both_adds_settings_and_label():
    settings, label = with_corrections(
        {"data_origin": "synthetic"}, "Sample", True, True, ["e1", "e2"], ["e1"], [(1.0, 2.0)]
    )
    assert settings == {
        "data_origin": "synthetic",
        "drainage": True,
        "drainage_evidence": ("e1", "e2"),
        "drainage_extra_positives": ((1.0, 2.0),),
        "ai_adjustment": True,
        "evidence": ["e1"],
    }
    assert label == "Sample + drainage model + AI evidence"
    assert active(settings) == {"drainage": True, "evidence": True}


def test_switching_off_removes_only_the_correction_settings():
    on, label = with_corrections({"allow_partial": True}, "Sample", True, True, ["e"], ["e"])
    off, label = with_corrections(on, label, False, False)
    assert off == {"allow_partial": True}
    assert label == "Sample"
    assert active(off) == {"drainage": False, "evidence": False}


def test_one_switch_keeps_the_other_off():
    settings, label = with_corrections({}, "Run + AI evidence", True, False, ["e"], ["e"])
    assert "ai_adjustment" not in settings and settings["drainage"] is True
    assert label == "Run + drainage model"


def test_switched_on_evidence_reaches_the_financial_engine(config):
    """Settings from the switch raise losses through damage, the EP curve, policy terms and reinsurance."""
    from decimal import Decimal
    from conftest import row
    from floodcat.ai.evidence import Evidence
    from floodcat.services.analysis import analyse

    ev = Evidence(
        evidence_id="e1", source="s", quote="q", event_date="2024-04-24", location_name="Kibera", lat=-1.3113,
        lon=36.789, location_method="nominatim", mechanism="drainage", confidence=0.9,
        independent_of_hotspot_list=True, approved=True, reviewer="r",
    )
    rows = [row(loc_id="NEAR", lat="-1.3113", lon="36.789", scores=(0.1, 0.2, 0.3, 0.4, 0.5))]
    settings, _ = with_corrections({}, "Run", False, True, [ev], [ev])
    report = analyse(rows, config, ai_adjustment=settings["ai_adjustment"], evidence=settings["evidence"])
    base, enhanced = report["runs"]["baseline"], report["runs"]["enhanced"]
    assert report["ai_contribution"]["changed_properties"] == 1
    assert Decimal(enhanced["aal"]["aal_kes"]) > Decimal(base["aal"]["aal_kes"])
    assert Decimal(enhanced["insured"]["aal"]["aal_kes"]) > Decimal(base["insured"]["aal"]["aal_kes"])
    assert "reinsurance" in enhanced
