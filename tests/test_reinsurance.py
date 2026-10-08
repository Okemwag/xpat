"""Financial engine: insured loss on by default, reinsurance (quota share + per-event excess of loss), property AAL."""

from decimal import Decimal
import numpy as np
import pytest
from floodcat.core.config import ModelConfig, load_config, merge_defaults
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.financial.reinsurance import apply, apply_array, layer_amounts
from floodcat.services.analysis import analyse

RI = {"enabled": True, "source": "test", "quota_share_cession": 0.3, "xol_retention_pct_of_tiv": 0.01,
      "xol_limit_pct_of_tiv": 0.03}
TIV = Decimal(100_000_000)  # retention 1,000,000; limit 3,000,000


def test_quota_share_then_excess_of_loss_by_hand():
    # Loss 5m: QS 30% = 1.5m; insurer keeps 3.5m; layer pays 3.5m − 1m = 2.5m (under its 3m limit); net 1m.
    s = apply(Decimal(5_000_000), RI, TIV)
    assert (s["quota_share"], s["excess_of_loss"], s["ceded"], s["net"]) == (
        Decimal(1_500_000), Decimal(2_500_000), Decimal(4_000_000), Decimal(1_000_000))
    small = apply(Decimal(1_000_000), RI, TIV)  # keeps 0.7m, below the 1m retention
    assert small["excess_of_loss"] == 0 and small["net"] == Decimal(700_000)
    big = apply(Decimal(20_000_000), RI, TIV)  # keeps 14m; layer exhausted at 3m
    assert big["excess_of_loss"] == Decimal(3_000_000) and big["net"] == Decimal(11_000_000)
    for s in (small, big):
        assert s["ceded"] + s["net"] == s["quota_share"] + s["excess_of_loss"] + s["net"]
    assert layer_amounts(RI, TIV) == (Decimal(1_000_000), Decimal(3_000_000))


def test_vectorised_split_matches_the_scalar_one():
    losses = np.array([0.0, 1e6, 5e6, 2e7])
    ceded, net = apply_array(losses, RI, TIV)
    for loss, c, n in zip(losses, ceded, net):
        s = apply(Decimal(str(loss)), RI, TIV)
        assert c == pytest.approx(float(s["ceded"])) and n == pytest.approx(float(s["net"]))


def test_programme_on_the_starter_portfolio(starter_rows, config):
    base = analyse(starter_rows, config)["runs"]["baseline"]
    ri = base["reinsurance"]
    assert ri["basis"] == "insured"
    insured = {p["tier"]: Decimal(p["loss_kes"]) for p in base["insured"]["ep_curve"]}
    for row in ri["by_tier"]:
        assert Decimal(row["loss_kes"]) == insured[row["tier"]]
        assert abs(Decimal(row["ceded"]) + Decimal(row["net"]) - Decimal(row["loss_kes"])) <= Decimal("0.02")
    for part in ("ceded", "net"):
        losses = [Decimal(p["loss_kes"]) for p in ri[part]["ep_curve"]]
        assert losses == sorted(losses)  # both still rise (or stay flat) with return period
    total = Decimal(ri["ceded"]["aal"]["aal_kes"]) + Decimal(ri["net"]["aal"]["aal_kes"])
    assert abs(total - Decimal(base["insured"]["aal"]["aal_kes"])) <= Decimal("0.05")


def test_reinsurance_works_on_gross_when_policy_terms_are_off(starter_rows, config):
    cfg = config.replace(policy_terms={"enabled": False, "deductible_pct_of_tiv": 0.0, "limit_pct_of_tiv": 1.0})
    base = analyse(starter_rows, cfg)["runs"]["baseline"]
    assert base["reinsurance"]["basis"] == "gross"
    assert [r["loss_kes"] for r in base["reinsurance"]["by_tier"]] == [p["loss_kes"] for p in base["ep_curve"]]
    off = analyse(starter_rows, config.replace(reinsurance={**config.reinsurance, "enabled": False}))
    assert "reinsurance" not in off["runs"]["baseline"]


def test_simulated_ceded_and_net_years_add_up_to_insured(starter_rows, config):
    from floodcat.financial.ylt import ylt_for_report

    report = analyse(starter_rows[:120], config)
    y = ylt_for_report(report, starter_rows[:120], config)["baseline"]
    assert {"gross", "insured", "ceded", "net"} <= set(y)
    total = Decimal(y["ceded"]["aal"]["aal_kes"]) + Decimal(y["net"]["aal"]["aal_kes"])
    assert abs(total - Decimal(y["insured"]["aal"]["aal_kes"])) <= Decimal("0.05")
    assert y["net"]["basis"] == "net" and y["ceded"]["basis"] == "ceded"


def test_reinsurance_config_rules(config):
    with pytest.raises(ModelError):
        config.replace(reinsurance={**config.reinsurance, "quota_share_cession": 1.0})
    with pytest.raises(ModelError):
        config.replace(reinsurance={**config.reinsurance, "quota_share_cession": 0.0, "xol_limit_pct_of_tiv": 0.0})
    legacy = {k: v for k, v in load_config().to_dict().items() if k not in ("reinsurance",)}
    assert ModelConfig(**merge_defaults(legacy)).reinsurance["enabled"] is False  # old house views keep their results


def test_property_aal_adds_up_to_the_portfolio_aal(starter_rows, config):
    base = analyse(starter_rows, config)["runs"]["baseline"]
    rows = base["property_aal"]
    total = sum(Decimal(r["aal_kes"]) for r in rows)
    assert abs(total - Decimal(base["aal"]["aal_kes"])) <= Decimal("0.01") * len(rows)
    insured = sum(Decimal(r["insured_aal_kes"]) for r in rows)
    assert abs(insured - Decimal(base["insured"]["aal"]["aal_kes"])) <= Decimal("0.01") * len(rows)
    assert [Decimal(r["aal_kes"]) for r in rows] == sorted((Decimal(r["aal_kes"]) for r in rows), reverse=True)
    assert all(Decimal(r["aal_kes"]) > 0 for r in rows)  # properties the map never flags are left out
    assert len(rows) == sum(1 for p in base["property_losses"][TIERS[-1]] if Decimal(p["loss_kes"]) > 0)


def test_ground_up_splits_into_deductible_above_limit_and_gross(starter_rows, config):
    cfg = config.replace(policy_terms={"enabled": True, "deductible_pct_of_tiv": 0.02, "limit_pct_of_tiv": 0.1})
    base = analyse(starter_rows, cfg)["runs"]["baseline"]
    ins = base["insured"]
    for p, g in zip(base["ep_curve"], ins["ep_curve"]):
        t = p["tier"]
        total = Decimal(ins["deductible_kes"][t]) + Decimal(ins["above_limit_kes"][t]) + Decimal(g["loss_kes"])
        assert abs(total - Decimal(p["loss_kes"])) <= Decimal("0.01") * len(base["property_losses"][t])
    assert Decimal(ins["above_limit_kes"]["common"]) > 0  # a 10% limit binds on badly damaged buildings


def test_waterfall_runs_from_ground_up_to_net(starter_rows, config):
    from floodcat.reporting.terms import NAME, TERMS, waterfall

    base = analyse(starter_rows, config)["runs"]["baseline"]
    for p in base["ep_curve"]:
        steps = dict((k, v) for k, _, v in waterfall(base, p["tier"]))
        assert steps["ground_up"] == Decimal(p["loss_kes"])
        assert abs(steps["ground_up"] + steps["deductible"] + steps["limit"] - steps["gross"]) <= Decimal(1)
        assert steps["gross"] + steps["quota_share"] + steps["cat_xl"] == steps["net"]
        split = next(t for t in base["reinsurance"]["by_tier"] if t["tier"] == p["tier"])
        assert abs(steps["net"] - Decimal(split["net"])) <= Decimal("0.01")
    assert [n for _, n, _ in TERMS] == ["Ground-up loss", "Deductible", "Limit", "Gross loss", "Quota share",
                                        "Catastrophe excess of loss", "Net loss"]
    assert "before insurance rules are applied" in dict((k, d) for k, _, d in TERMS)["ground_up"] and NAME["net"] == "Net loss"
