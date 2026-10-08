from decimal import Decimal
import pytest
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.exposure.validation import validate_rows
from floodcat.services.analysis import analyse
from conftest import row


def terms(config, deductible=0.01, limit=0.5):
    return config.replace(
        policy_terms={
            "enabled": True,
            "deductible_pct_of_tiv": deductible,
            "limit_pct_of_tiv": limit,
        }
    )


def test_insured_loss_is_on_by_default_and_can_be_switched_off(config):
    """Objective 1 asks for the insured loss, so every default run carries it beside the gross loss."""
    on = analyse([row()], config)["runs"]["baseline"]
    assert "insured" in on and "insured_loss_kes" in on["property_losses"]["common"][0]
    gross = Decimal(on["ep_curve"][-1]["loss_kes"])
    assert Decimal(on["insured"]["ep_curve"][-1]["loss_kes"]) <= gross
    off = analyse([row()], terms(config, 0.0, 1.0).replace(
        policy_terms={"enabled": False, "deductible_pct_of_tiv": 0.0, "limit_pct_of_tiv": 1.0}))["runs"]["baseline"]
    assert "insured" not in off and "insured_loss_kes" not in off["property_losses"]["common"][0]


def test_insured_loss_applies_deductible_and_limit(config):
    # common score 2/3 → 1.0 m → 38% damage on masonry → gross 380,000 on TIV 1,000,000.
    rows = [row(tiv="1000000", scores=(0, 0, 0, 0, 2 / 3))]
    assert (
        analyse(rows, terms(config, 0.05, 0.5))["runs"]["baseline"]["property_losses"][
            "common"
        ][0]["insured_loss_kes"]
        == "330000.00"
    )
    assert (
        analyse(rows, terms(config, 0.05, 0.2))["runs"]["baseline"]["property_losses"][
            "common"
        ][0]["insured_loss_kes"]
        == "150000.00"
    )
    assert (
        analyse(rows, terms(config, 0.5, 0.9))["runs"]["baseline"]["property_losses"][
            "common"
        ][0]["insured_loss_kes"]
        == "0.00"
    )


def test_row_terms_override_portfolio_terms(config):
    rows = [
        row(
            tiv="1000000",
            scores=(0, 0, 0, 0, 2 / 3),
            deductible_kes="100k",
            limit_kes="200k",
        )
    ]
    assert (
        analyse(rows, terms(config))["runs"]["baseline"]["property_losses"]["common"][
            0
        ]["insured_loss_kes"]
        == "100000.00"
    )


def test_invalid_terms_rejected(config):
    with pytest.raises(ModelError):
        terms(config, 0.5, 0.4)
    _, issues = validate_rows([row(deductible_kes="300k", limit_kes="200k")])
    assert "invalid_policy_terms" in {i["code"] for i in issues}


def test_insured_curve_rises_and_never_exceeds_gross(starter_rows, config):
    run = analyse(starter_rows, terms(config))["runs"]["baseline"]
    insured = [Decimal(p["loss_kes"]) for p in run["insured"]["ep_curve"]]
    gross = [Decimal(p["loss_kes"]) for p in run["ep_curve"]]
    assert all(a <= b for a, b in zip(insured, insured[1:])) and all(
        i <= g for i, g in zip(insured, gross)
    )


np = pytest.importorskip("numpy")
from floodcat.financial.uncertainty import uncertainty_ranges


@pytest.fixture(scope="module")
def sample(starter_rows):
    from floodcat.core.config import load_config

    config = load_config()
    return analyse(starter_rows, config), config


def test_ranges_bracket_the_deterministic_loss(sample, starter_rows):
    report, config = sample
    sim = uncertainty_ranges(report, starter_rows, config)["baseline"]["gross"]
    for point in report["runs"]["baseline"]["ep_curve"]:
        s = sim["by_tier"][point["tier"]]
        assert (
            Decimal(s["p_low_kes"])
            < Decimal(point["loss_kes"])
            < Decimal(s["p_high_kes"])
        )
        assert abs(Decimal(s["mean_kes"]) / Decimal(point["loss_kes"]) - 1) < Decimal(
            "0.05"
        )


def test_simulated_curve_rises_with_rarity_and_is_reproducible(sample, starter_rows):
    report, config = sample
    a = uncertainty_ranges(report, starter_rows, config)["baseline"]["gross"]["by_tier"]
    b = uncertainty_ranges(report, starter_rows, config)["baseline"]["gross"]["by_tier"]
    assert a == b
    for key in ("p_low_kes", "median_kes", "p_high_kes"):
        values = [Decimal(a[t][key]) for t in TIERS]
        assert all(x <= y for x, y in zip(values, values[1:]))


def test_zero_sigma_collapses_to_deterministic(sample, starter_rows):
    report, config = sample
    flat = config.replace(uncertainty={**config.uncertainty, "damage_sigma": 0.0})
    s = uncertainty_ranges(report, starter_rows, flat)["baseline"]["gross"]["by_tier"][
        "common"
    ]
    det = Decimal(report["runs"]["baseline"]["ep_curve"][-1]["loss_kes"])
    assert (
        abs(Decimal(s["p_low_kes"]) - det) < 1
        and abs(Decimal(s["p_high_kes"]) - det) < 1
    )


def test_correlation_widens_portfolio_range(sample, starter_rows):
    report, config = sample

    def width(rho):
        s = uncertainty_ranges(
            report,
            starter_rows,
            config.replace(uncertainty={**config.uncertainty, "correlation": rho}),
        )["baseline"]["gross"]["by_tier"]["common"]
        return Decimal(s["p_high_kes"]) - Decimal(s["p_low_kes"])

    assert width(0.0) < width(1.0)


def test_insured_ranges_with_policy_terms(starter_rows, config):
    cfg = terms(config)
    report = analyse(starter_rows, cfg)
    sim = uncertainty_ranges(report, starter_rows, cfg)["baseline"]
    assert Decimal(sim["insured"]["by_tier"]["common"]["mean_kes"]) < Decimal(
        sim["gross"]["by_tier"]["common"]["mean_kes"]
    )


def test_bad_uncertainty_config_rejected(config):
    for bad in (
        {"trials": 5},
        {"correlation": 1.5},
        {"interval_pct": [95, 5]},
        {"trials": True},
    ):
        with pytest.raises(ModelError):
            config.replace(uncertainty={**config.uncertainty, **bad})


from floodcat.financial.ylt import ylt_for_report


@pytest.fixture(scope="module")
def ylt(sample, starter_rows):
    report, config = sample
    return (
        ylt_for_report(report, starter_rows, config)["baseline"]["gross"],
        report,
        config,
    )


def test_ylt_mean_matches_scenario_aal(ylt):
    sim, report, _ = ylt
    assert abs(
        Decimal(sim["aal"]["aal_kes"])
        / Decimal(report["runs"]["baseline"]["aal"]["aal_kes"])
        - 1
    ) < Decimal("0.05")
    assert (
        Decimal(sim["aal"]["band_low_kes"])
        <= Decimal(sim["aal"]["aal_kes"])
        <= Decimal(sim["aal"]["band_high_kes"])
    )


def test_ylt_curve_rises_and_band_brackets_it(ylt):
    sim, _, _ = ylt
    losses = [Decimal(p["loss_kes"]) for p in sim["curve"]]
    assert all(a <= b for a, b in zip(losses, losses[1:]))
    assert all(
        Decimal(p["band_low_kes"])
        <= Decimal(p["loss_kes"])
        <= Decimal(p["band_high_kes"])
        for p in sim["curve"]
    )
    assert sim["curve"][-1]["return_period_years"] == 10000


def test_ylt_zero_loss_share_follows_assumption(ylt):
    sim, _, config = ylt
    assert (
        abs(
            sim["zero_loss_years"] / sim["years"]
            - (1 - 1 / config.aal_zero_loss_return_period)
        )
        < 0.02
    )


def test_ylt_tracks_scenario_points(ylt):
    sim, report, _ = ylt
    table = {p["return_period_years"]: Decimal(p["loss_kes"]) for p in sim["table"]}
    for point in report["runs"]["baseline"]["ep_curve"]:
        assert abs(
            table[point["return_period_years"]] / Decimal(point["loss_kes"]) - 1
        ) < Decimal("0.25")


def test_ylt_reproducible(sample, starter_rows):
    report, config = sample
    assert ylt_for_report(report, starter_rows, config) == ylt_for_report(
        report, starter_rows, config
    )


def test_bad_ylt_config_rejected(config):
    for bad in ({"years": 10}, {"bootstrap": 1}, {"band_pct": [95, 5]}):
        with pytest.raises(ModelError):
            config.replace(year_loss_table={**config.year_loss_table, **bad})
