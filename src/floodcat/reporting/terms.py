"""The financial terms every results view uses, with the definitions given to the hackathon teams.

Internal result keys predate these names and are kept for compatibility:
  runs[...]["ep_curve"] / ["aal"]          -> Ground-up loss
  runs[...]["insured"]                     -> Gross loss (after deductible and limit)
  runs[...]["reinsurance"]["ceded"]        -> Reinsurance recoveries (quota share + catastrophe excess of loss)
  runs[...]["reinsurance"]["net"]          -> Net loss
"""

TERMS = (
    ("ground_up", "Ground-up loss",
     "The total physical damage caused to a building before insurance rules are applied."),
    ("deductible", "Deductible",
     "The part of the loss that the building owner must pay themselves before the insurer pays."),
    ("limit", "Limit",
     "The maximum amount the insurer will pay for the building."),
    ("gross", "Gross loss",
     "The amount the insurer is responsible for paying after applying the deductible and limit."),
    ("quota_share", "Quota share",
     "A reinsurance arrangement where the insurer and reinsurer share every loss by an agreed percentage. "
     "For example, a 25% quota share means the reinsurer pays 25% of the gross loss."),
    ("cat_xl", "Catastrophe excess of loss",
     "Reinsurance that protects the insurer when the total loss from one catastrophe becomes large. The reinsurer "
     "starts paying after the loss passes an agreed threshold and pays up to an agreed maximum."),
    ("net", "Net loss",
     "The amount of the loss that remains with the insurer after payments from reinsurers."),
)
NAME = {key: name for key, name, _ in TERMS}
DEFINITION = {key: text for key, _, text in TERMS}

# Loss bases as stored internally -> the name shown to people.
BASIS = {
    "gross": "Ground-up loss",
    "insured": "Gross loss",
    "ceded": "Reinsurance recoveries",
    "net": "Net loss",
}


def waterfall(run, tier):
    """Ground-up → deductible → above the limit → gross → quota share → catastrophe excess of loss → net, for one scenario.

    Returns [(key, label, amount)] where deductions are negative; the steps add up from ground-up to net. Missing
    layers (policy terms or reinsurance off) appear as zero so the picture always has the same shape.
    """
    from decimal import Decimal

    ground_up = Decimal(next(p["loss_kes"] for p in run["ep_curve"] if p["tier"] == tier))
    ins = run.get("insured")
    deductible = Decimal(ins["deductible_kes"][tier]) if ins and "deductible_kes" in ins else Decimal(0)
    above = Decimal(ins["above_limit_kes"][tier]) if ins and "above_limit_kes" in ins else Decimal(0)
    gross = Decimal(next(p["loss_kes"] for p in ins["ep_curve"] if p["tier"] == tier)) if ins else ground_up
    if ins and "deductible_kes" not in ins:  # results saved before the split existed
        deductible = ground_up - gross
    ri = next((t for t in run["reinsurance"]["by_tier"] if t["tier"] == tier), None) if "reinsurance" in run else None
    qs = Decimal(ri["quota_share"]) if ri else Decimal(0)
    xl = Decimal(ri["excess_of_loss"]) if ri else Decimal(0)
    return [
        ("ground_up", NAME["ground_up"], ground_up),
        ("deductible", NAME["deductible"], -deductible),
        ("limit", "Above the limit", -above),
        ("gross", NAME["gross"], gross),
        ("quota_share", NAME["quota_share"], -qs),
        ("cat_xl", NAME["cat_xl"], -xl),
        ("net", NAME["net"], gross - qs - xl),
    ]
