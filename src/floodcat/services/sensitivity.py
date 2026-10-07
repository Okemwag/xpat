"""Explicit assumption scenarios, not statistical confidence intervals."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation

from ..core.config import load_config
from ..core.constants import TIERS
from .analysis import analyse


def assumption_sensitivity(rows, config=None, provider=None):
    config = config or load_config()

    def run_case(rows, config):
        return analyse(rows, config, provider, allow_partial=True)

    cases = {}

    def summarize(report):
        run = report["runs"]["baseline"]
        return {"loss_kes_by_tier": {point["tier"]: point["loss_kes"] for point in run["ep_curve"]},
                "aal_kes": run["aal"]["aal_kes"]}

    cases["base"] = summarize(run_case(rows, config))

    alternate_rows = deepcopy(rows)
    for row in alternate_rows:
        if row.get("floor_area_m2") in (None, "") or row.get("cost_per_m2_kes") in (None, ""):
            alternate_rows = None
            break
        try:
            row["tiv_kes"] = str(Decimal(str(row["floor_area_m2"]).replace(",", "")) *
                                 Decimal(str(row["cost_per_m2_kes"]).replace(",", "")))
        except InvalidOperation:
            alternate_rows = None
            break
    if alternate_rows is not None:
        cases["area_times_cost_tiv"] = summarize(run_case(alternate_rows, config))

    for depth in config.depth_sensitivity_m:
        cases[f"max_depth_{depth:g}m"] = summarize(run_case(rows, config.replace(max_depth_m=depth)))

    doubled = config.replace(return_periods={tier: config.return_periods[tier] * 2 for tier in TIERS})
    cases["doubled_return_periods"] = summarize(run_case(rows, doubled))
    return {"status": "assumption_scenarios_not_confidence_intervals",
            "cases": cases,
            "notes": ["Area-times-cost is an alternative TIV interpretation, not a correction.",
                      "Max depth rescales the score-to-depth assumption; the score itself is unchanged.",
                      "Doubling return periods leaves scenario losses unchanged and lowers AAL; the zero-loss point stays fixed."]}
