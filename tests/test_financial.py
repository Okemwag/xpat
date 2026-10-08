from decimal import Decimal
import pytest
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.financial.ep import average_annual_loss, ep_curve
from floodcat.financial.loss import total_loss
from floodcat.hazard.hotspots import load_hotspots
from floodcat.services.analysis import analyse
from conftest import DATA, row


@pytest.fixture(scope="module")
def starter_report(starter_rows):
    from floodcat.core.config import load_config

    return analyse(
        starter_rows,
        load_config(),
        hotspots=load_hotspots(DATA / "nairobi_hotspots_geocoded.csv"),
    )


def test_portfolio_loss_rises_with_return_period(starter_report):
    losses = [
        Decimal(p["loss_kes"]) for p in starter_report["runs"]["baseline"]["ep_curve"]
    ]
    rps = [
        p["return_period_years"] for p in starter_report["runs"]["baseline"]["ep_curve"]
    ]
    assert rps == sorted(rps)
    assert all(a < b for a, b in zip(losses, losses[1:]))


def test_building_losses_sum_to_portfolio_loss(starter_report):
    run = starter_report["runs"]["baseline"]
    for point in run["ep_curve"]:
        rows = run["property_losses"][point["tier"]]
        assert total_loss(rows) == Decimal(point["loss_kes"])
        for dimension in ("construction", "hotspot_area", "geographic_grid"):
            assert sum(
                Decimal(i["loss_kes"])
                for i in run["breakdowns"][point["tier"]][dimension]
            ) == Decimal(point["loss_kes"])


def test_synthetic_label_survives_into_loss_rows(starter_report):
    for rows in starter_report["runs"]["baseline"]["property_losses"].values():
        assert all(r["synthetic"] is True and r["exposure_source"] for r in rows)
    assert any(p["label"] == "SYNTHETIC" for p in starter_report["provenance"])


def test_damage_never_exceeds_class_cap(starter_report, config):
    for rows in starter_report["runs"]["baseline"]["property_losses"].values():
        for r in rows:
            assert (
                0
                <= r["damage_ratio"]
                <= config.class_adjustments[r["housing_class"]]["damage_cap"]
            )


def test_aal_matches_hand_calculation(config):
    totals = dict(zip(TIERS, map(Decimal, (100, 200, 300, 400, 500))))
    # AEP points 0.5→0, 0.1→100, 0.04→200, 0.02→300, 0.01→400, 0.004→500, then 500 held to 0.
    expected = (
        Decimal("0.4") * 50
        + Decimal("0.06") * 150
        + Decimal("0.02") * 250
        + Decimal("0.01") * 350
        + Decimal("0.006") * 450
        + Decimal("0.004") * 500
    )
    assert Decimal(average_annual_loss(totals, config)["aal_kes"]) == expected.quantize(
        Decimal("0.01")
    )


def test_decreasing_loss_is_rejected_not_reordered(config):
    totals = dict(zip(TIERS, map(Decimal, (100, 50, 300, 400, 500))))
    with pytest.raises(ModelError):
        ep_curve(totals, config)
    with pytest.raises(ModelError):
        average_annual_loss(totals, config)


def test_single_property_loss_is_tiv_times_damage(config):
    report = analyse([row(tiv="1000000", scores=(0, 0, 0, 0, 2 / 3))], config)
    common = report["runs"]["baseline"]["property_losses"]["common"][0]
    # 2/3 × 1.5 m = 1.0 m on masonry → JRC 0.38.
    assert common["damage_ratio"] == pytest.approx(0.38)
    assert Decimal(common["loss_kes"]) == Decimal("380000.00")


def test_invalid_records_require_explicit_partial_analysis(config):
    rows = [row(), row(loc_id="T-2", housing_class="castle")]
    with pytest.raises(ModelError):
        analyse(rows, config)
    report = analyse(rows, config, allow_partial=True)
    assert report["partial"] and report["modelled_count"] == 1


def test_real_portfolio_is_modelled_and_labelled_real(config):
    report = analyse([row(synthetic="False", source="broker submission")], config)
    assert report["exposure_origin"] == {"real": 1, "synthetic": 0, "labels": ["REAL"]}
    assert report["provenance"][0]["label"] == "REAL"
    assert (
        report["runs"]["baseline"]["property_losses"]["common"][0]["synthetic"] is False
    )


def test_mixed_portfolio_labelled_both(config):
    report = analyse([row(), row(loc_id="T-2", synthetic="False")], config)
    assert (
        report["exposure_origin"]["labels"] == ["REAL", "SYNTHETIC"]
        and report["provenance"][0]["label"] == "REAL+SYNTHETIC"
    )


def test_synthetic_only_deployment_rejects_real(config):
    with pytest.raises(ModelError):
        analyse([row(synthetic="False")], config, synthetic_only=True)
