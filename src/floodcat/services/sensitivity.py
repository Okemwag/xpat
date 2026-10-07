"""Explicit assumption scenarios, not statistical confidence intervals."""

from copy import deepcopy
from decimal import Decimal

from ..core.config import ModelConfig
from ..core.constants import TIERS
from .analysis import analyse


def assumption_sensitivity(rows, config=None):
    config = config or ModelConfig()
    cases = {}

    def summarize(report):
        return {point["tier"]: point["loss_kes"]
                for point in report["runs"]["baseline"]["ep_curve"]}

    cases["supplied_tiv"] = summarize(analyse(rows, config))

    alternate_rows = deepcopy(rows)
    for row in alternate_rows:
        if row.get("floor_area_m2") in (None, "") or row.get("cost_per_m2_kes") in (None, ""):
            raise ValueError("Area-times-cost sensitivity requires area and cost for every asset")
        row["tiv_kes"] = str(Decimal(str(row["floor_area_m2"])) *
                             Decimal(str(row["cost_per_m2_kes"])))
    cases["area_times_cost_tiv"] = summarize(analyse(alternate_rows, config))

    for factor, label in ((0.75, "vulnerability_75_percent"),
                          (1.25, "vulnerability_125_percent")):
        settings = config.to_dict()
        settings["curves"] = {name: [min(.95, value * factor) for value in curve]
                              for name, curve in config.curves.items()}
        cases[label] = summarize(analyse(rows, ModelConfig(**settings)))

    rp_settings = config.to_dict()
    rp_settings["return_periods"] = {tier: config.return_periods[tier] * 2 for tier in TIERS}
    alternate_rp = analyse(rows, ModelConfig(**rp_settings))["runs"]["baseline"]["ep_curve"]
    return {"status": "assumption_scenarios_not_confidence_intervals",
            "loss_kes_by_tier": cases,
            "doubled_return_period_mapping": [
                {"tier": p["tier"], "return_period_years": p["return_period_years"],
                 "annual_exceedance_probability": p["annual_exceedance_probability"],
                 "loss_kes": p["loss_kes"]} for p in alternate_rp],
            "notes": ["Area-times-cost is an alternative TIV interpretation, not a correction.",
                      "Damage-curve scaling is illustrative and capped at 0.95.",
                      "Changing assumed return periods moves curve labels, not scenario losses."]}
