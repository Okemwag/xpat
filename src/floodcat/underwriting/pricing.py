"""Pricing and premium adequacy for one risk at 100%, from a recommendation (underwriting/decision.recommend).

Technical premium build-up (the organisation's own rules, ASSUMPTION):

    expected annual loss (modelled AAL)
  + uncertainty load        = AAL × uncertainty_load            (the model is uncalibrated)
  = risk premium
  + expenses and margin     = risk premium × (1 / target_loss_ratio − 1)
  = technical premium       = AAL × (1 + uncertainty_load) / target_loss_ratio

Adequacy = offered premium ÷ technical premium. Market measures (rate per mille of insured value, rate on line against the
PML loss, payback years) are shown for comparison with how underwriters usually quote; none of them is a market benchmark.
"""

from decimal import Decimal, ROUND_HALF_UP


def _d(x):
    return Decimal(str(x))


def _r(x):
    return _d(x).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def breakdown(rec):
    f, rules = rec["figures"], rec["rules"]
    aal = _d(f["aal_100_kes"])
    load = aal * _d(rules["uncertainty_load"])
    risk_premium = aal + load
    technical = _d(f["technical_premium_100_kes"])
    margin = technical - risk_premium
    offered = _d(rec["premium_100_kes"])
    tiv, pml = _d(f["tiv_100_kes"]), _d(f["pml_100_kes"])
    adequacy = f["price_adequacy"]
    floor = technical * _d(rules["decline_below_adequacy"])
    if adequacy is None:
        verdict, words = (
            "untested",
            "The model shows no annual loss here, so the price cannot be tested against it.",
        )
    elif adequacy >= 1:
        verdict, words = (
            "adequate",
            f"The offered premium covers the technical premium ({adequacy:.0%}).",
        )
    elif adequacy >= rules["decline_below_adequacy"]:
        verdict, words = (
            "thin",
            (
                f"The offered premium is {adequacy:.0%} of technical: acceptable under the rules but thin. "
                f"{_kes(technical - offered)} more would make it fully adequate."
            ),
        )
    else:
        verdict, words = (
            "inadequate",
            (
                f"The offered premium is {adequacy:.0%} of technical, below the {rules['decline_below_adequacy']:.0%} "
                f"the rules accept. It needs to rise by at least {_kes(floor - offered)} to be considered."
            ),
        )
    return {
        "steps": [
            {
                "step": "Expected annual loss (modelled)",
                "amount_kes": _r(aal),
                "kind": "loss",
            },
            {
                "step": f"Uncertainty load ({rules['uncertainty_load']:.0%} of annual loss)",
                "amount_kes": _r(load),
                "kind": "load",
            },
            {
                "step": f"Expenses and margin (to a {rules['target_loss_ratio']:.0%} target loss ratio)",
                "amount_kes": _r(margin),
                "kind": "load",
            },
            {"step": "Technical premium", "amount_kes": _r(technical), "kind": "total"},
        ],
        "technical_kes": _r(technical),
        "offered_kes": _r(offered),
        "adequacy": adequacy,
        "verdict": verdict,
        "verdict_text": words,
        "shortfall_kes": _r(max(Decimal(0), technical - offered)),
        "minimum_acceptable_kes": _r(floor),
        "rate_per_mille_offered": float(offered / tiv * 1000) if tiv else None,
        "rate_per_mille_technical": float(technical / tiv * 1000) if tiv else None,
        "rate_on_line_pct": float(offered / pml * 100) if pml else None,
        "payback_years": float(pml / offered) if offered else None,
        "expected_loss_ratio": f["expected_loss_ratio"],
        "pml_return_period": f["pml_return_period"],
        "labels": ["ASSUMPTION"],
    }


def _kes(value):
    from .decision import _kes as fmt

    return fmt(value)
