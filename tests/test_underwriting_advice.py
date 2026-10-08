"""Pricing and premium adequacy, accumulation warnings (this risk and the written book) and the advice built from them."""

from decimal import Decimal
import pytest
from floodcat.services.analysis import analyse
from floodcat.underwriting.accumulation import area_exposure, assess, book_exposure
from floodcat.underwriting.advice import advise
from floodcat.underwriting.decision import default_rules, recommend
from floodcat.underwriting.pricing import breakdown
from conftest import row


def portfolio(config, crowded=8, spread=2, synthetic="True"):
    """Most value in one 1 km area (Mathare), a little elsewhere."""
    rows = [
        row(
            f"C-{i}",
            lat=str(-1.2600 + i * 0.0002),
            lon="36.8580",
            tiv="20000000",
            synthetic=synthetic,
            scores=(0.2, 0.3, 0.4, 0.5, 0.6),
        )
        for i in range(crowded)
    ]
    rows += [
        row(
            f"S-{i}",
            lat=str(-1.33 - i * 0.02),
            lon=str(36.75 + i * 0.03),
            tiv="5000000",
            synthetic=synthetic,
            scores=(0.0, 0.1, 0.2, 0.3, 0.4),
        )
        for i in range(spread)
    ]
    # Gross-basis fixtures: policy terms are on by default, and pricing reads the insured loss whenever a run has one.
    gross = config.replace(policy_terms={**config.policy_terms, "enabled": False})
    return analyse(rows, gross)


RULES = {
    **default_rules(),
    "target_loss_ratio": 0.5,
    "uncertainty_load": 0.5,
    "decline_below_adequacy": 0.75,
    "max_pml_kes": 1e12,
    "max_line_tiv_kes": 1e15,
    "max_area_tiv_pct": 35,
}


def technical(report):
    return (
        Decimal(report["runs"]["baseline"]["aal"]["aal_kes"])
        * Decimal("1.5")
        / Decimal("0.5")
    )


def test_pricing_build_up_adds_up_and_reports_adequacy(config):
    report = portfolio(config)
    tech = technical(report)
    rec = recommend(report, float(tech * Decimal("0.9")), 10, RULES)
    p = breakdown(rec)
    steps = {s["kind"]: s for s in p["steps"]}
    assert sum(s["amount_kes"] for s in p["steps"][:3]) == pytest.approx(
        float(p["technical_kes"]), abs=2
    )
    assert (
        p["verdict"] == "thin"
        and p["shortfall_kes"] > 0
        and "more would make it fully adequate" in p["verdict_text"]
    )
    assert p["minimum_acceptable_kes"] == pytest.approx(float(tech) * 0.75, abs=2)
    assert p["rate_per_mille_offered"] < p["rate_per_mille_technical"]
    assert p["payback_years"] > 0 and p["rate_on_line_pct"] > 0
    assert (
        breakdown(recommend(report, float(tech * 2), 10, RULES))["verdict"]
        == "adequate"
    )
    assert (
        breakdown(recommend(report, float(tech * Decimal("0.5")), 10, RULES))["verdict"]
        == "inadequate"
    )


def test_concentration_is_warned_and_area_limit_caps_the_share(config):
    report = portfolio(config)
    tech = technical(report)
    areas = area_exposure(report, "baseline", "gross", 250)
    crowded = max(areas.values(), key=lambda v: v["tiv"])
    rules = {
        **RULES,
        "max_area_pml_kes": float(crowded["loss"]) * 0.2,
    }  # room for 20% of the crowded area
    rec = recommend(report, float(tech * 2), 50, rules)
    acc = rec["accumulation"]
    assert rec["outcome"] == "share" and rec["recommended_share_pct"] <= 20
    assert "Area accumulation limit" in [l["rule"] for l in rec["share_limits"]]
    assert any(
        c["code"] == "concentration" and c["status"] == "warn" for c in rec["checks"]
    )
    assert (
        acc["warnings"][0]["level"] == "limit" and acc["areas"][0]["tiv_share_pct"] > 35
    )
    assert all(
        not a["over_limit"] for a in acc["areas"]
    )  # at the recommended share we fit


def test_written_book_reduces_room_in_the_same_area(config):
    report = portfolio(config)
    tech = technical(report)
    crowded = max(
        area_exposure(report, "baseline", "gross", 250).values(), key=lambda v: v["tiv"]
    )
    rules = {**RULES, "max_area_pml_kes": float(crowded["loss"]) * 0.3}
    alone = recommend(report, float(tech * 2), 30, rules)
    book = book_exposure(
        [(report, "baseline", "gross", 250, 20.0)]
    )  # we already wrote 20% of a similar risk there
    with_book = recommend(report, float(tech * 2), 30, rules, book=book, book_written=1)
    assert with_book["recommended_share_pct"] < alone["recommended_share_pct"]
    assert with_book["accumulation"]["book_risks"] == 1
    assert any(
        "already hold" in w["text"] for w in with_book["accumulation"]["warnings"]
    )


def test_advice_is_sober_and_traceable(config):
    report = portfolio(config)
    tech = technical(report)
    thin = recommend(report, float(tech * Decimal("0.9")), 10, RULES)
    a = advise(thin, breakdown(thin), report)
    assert a["headline"].startswith("Write") and a["outcome"] == "share"
    assert any(
        "technical premium" in c for c in a["conditions"]
    )  # price up towards technical
    assert any(
        "synthetic data" in c for c in a["conditions"]
    )  # never quote on synthetic data
    assert any("drains" in t for t in a["trust"]) and a["trust_level"] == "low"
    assert not any(
        word in " ".join([a["headline"], *a["reasons"], *a["conditions"]]).lower()
        for word in ("safe", "guarantee", "accurate")
    )
    low = recommend(report, float(tech * Decimal("0.5")), 10, RULES)
    d = advise(low, breakdown(low), report)
    assert (
        d["outcome"] == "decline"
        and "reconsider at a 100% premium of at least" in d["headline"]
    )


def test_accumulation_without_property_results_is_reported_not_guessed():
    from test_underwriting import RULES as R, report as small

    acc = assess(small(), "baseline", "gross", 250, R)
    assert (
        acc["available"] is False
        and acc["max_share_pct"] is None
        and acc["areas"] == []
    )


def test_written_book_is_built_from_accepted_decisions_only(
    tmp_path, monkeypatch, config
):
    pytest.importorskip("rasterio")
    from floodcat.platform import data, identity
    from floodcat.platform.service import Platform

    monkeypatch.setenv("FLOODCAT_BREACH_CHECK", "0")
    monkeypatch.setenv("FLOODCAT_STORE_DIR", str(tmp_path))
    plat = Platform(f"sqlite:///{tmp_path}/platform.db")
    with plat.tx() as c:
        org_id, raw = identity.create_organisation(c, None, "Book Re", "head@book.re")
        user_id, _ = identity.accept_invitation(
            c, raw, display_name="Head", password="a long and unusual passphrase 42"
        )
        c.execute(
            identity.memberships.update()
            .where(identity.memberships.c.user_id == user_id)
            .values(roles=["head_uw"])
        )
        raw_s, _ = identity.start_session(c, user_id, org_id)
        p, _ = identity.resolve_session(c, raw_s)
        written, declined = portfolio(config), portfolio(config)
        for rep, label in ((written, "written"), (declined, "declined")):
            data.save_run(c, p, rep, [], label)
        tech = float(technical(written)) * 2
        data.record_decision(
            c,
            p,
            written["analysis_id"],
            tech,
            10,
            "accept",
            reason="Written for the book accumulation test.",
        )
        data.record_decision(
            c,
            p,
            declined["analysis_id"],
            tech,
            10,
            "decline",
            reason="Declined for the book accumulation test.",
        )
        book, count = data.written_book(c, p, 250)
        assert count == 1
        crowded = max(
            area_exposure(written, "baseline", "gross", 250).items(),
            key=lambda kv: kv[1]["tiv"],
        )
        assert book[crowded[0]]["loss"] == pytest.approx(
            crowded[1]["loss"] * Decimal("0.1")
        )
        assert (
            data.written_book(c, p, 250, exclude_run_id=written["analysis_id"])[1] == 0
        )


def test_single_site_risk_is_not_warned_as_concentrated(config):
    """One building is in one 1 km area by definition; the spread rule is for schedules, not single-site risks."""
    report = portfolio(config, crowded=1, spread=0)
    rec = recommend(report, 50_000_000, 10, RULES)
    acc = rec["accumulation"]
    assert not any(a["concentrated"] for a in acc["areas"])
    assert not any(c["code"] == "concentration" and c["status"] == "warn" for c in rec["checks"])
    assert any("single-site risk" in w["text"] and w["level"] == "info" for w in acc["warnings"])
