"""Sound advice for the underwriter: one clear recommendation, the reasons behind it, the conditions to write it on, and
how far to trust it.

Written by fixed rules from the recommendation, the pricing breakdown, the accumulation check and the analysis itself, so
the same inputs always give the same advice and every sentence can be traced to a number. It is deliberately sober: it
never calls a risk safe, never claims accuracy, and says plainly when the model cannot see something. The AI explanation
on the decision page is separate and optional; the underwriter makes and records the decision.
"""

from decimal import Decimal
from .decision import _kes


def _zero_score_share(report, run):
    """Share of insured value at properties the hazard map does not flag in any tier."""
    rows = report.get("runs", {}).get(run, {}).get("property_losses", {})
    rarest = rows.get("common") if rows else None
    if not rarest:
        return None
    total = sum(Decimal(str(r["tiv_kes"])) for r in rarest)
    zero = sum(Decimal(str(r["tiv_kes"])) for r in rarest if r["hazard_score"] == 0)
    return float(zero / total * 100) if total else None


def advise(rec, pricing, report):
    f, rules, acc = rec["figures"], rec["rules"], rec.get("accumulation") or {}
    share, offered = rec["recommended_share_pct"], rec["offered_share_pct"]
    checks = {c["code"]: c for c in rec["checks"]}

    # 1. The recommendation in one sentence.
    if rec["outcome"] == "accept":
        headline = f"Write the offered {offered:g}% at the offered premium."
    elif rec["outcome"] == "share":
        headline = f"Write {share:g}% rather than the offered {offered:g}%."
    else:
        headline = "Decline at these terms."
        if checks.get("price", {}).get("status") == "fail":
            headline = f"Decline at this price; reconsider at a 100% premium of at least {_kes(pricing['minimum_acceptable_kes'])}."
        elif checks.get("data", {}).get("status") == "fail":
            headline = "Decline until the schedule is complete enough to model."

    # 2. Why, from the rules that decided it (most important first).
    reasons = []
    order = ("price", "data", "min_share", "pml", "area", "line", "concentration")
    for code in order:
        c = checks.get(code)
        if c and c["status"] in ("fail", "limit"):
            reasons.append(c["detail"])
    price_decided = checks.get("price", {}).get("status") in ("fail", "limit")
    if not reasons:
        reasons.append(f"Every rule passes at {offered:g}%. {pricing['verdict_text']}")
    elif not price_decided:
        reasons.append(pricing["verdict_text"])

    # 3. Conditions (subjectivities) to write it on.
    conditions = []
    if rec["outcome"] != "decline":
        if pricing["verdict"] == "thin":
            conditions.append(
                f"Ask for the premium to move towards the technical premium of {_kes(pricing['technical_kes'])} "
                f"(a further {_kes(pricing['shortfall_kes'])} at 100%)."
            )
        crowded = [a for a in acc.get("areas", []) if a.get("concentrated")]
        if crowded:
            conditions.append(
                f"{crowded[0]['area']} holds {crowded[0]['tiv_share_pct']:.0f}% of the insured value: confirm the "
                "locations there and consider a sub-limit for that area."
            )
        if (
            acc.get("max_share_pct") is not None
            and acc["max_share_pct"] < 100
            and acc.get("binding_area")
        ):
            conditions.append(
                f"Keep the line within the area accumulation limit in {acc['binding_area']}; review it if more risks "
                "there are written first."
            )
    if f.get("unmodelled_pct", 0) > 0:
        conditions.append(
            f"{f['unmodelled_pct']:.0f}% of submitted records could not be modelled: get corrected locations or values "
            "before binding, or exclude them from cover."
        )
    if rec.get("origin") and "SYNTHETIC" in rec["origin"]:
        conditions.append(
            "This analysis uses synthetic data: do not quote or bind on it."
        )
    zero = _zero_score_share(report, rec["run"])
    if zero and zero >= 10:
        conditions.append(
            f"{zero:.0f}% of insured value sits where the hazard map shows no flood score. The map cannot see drainage "
            "failures, so ask the broker about flood history at those addresses."
        )

    # 4. How far to trust it.
    trust = [
        "Hazard is a terrain-and-river proxy that cannot see blocked or overwhelmed drains.",
        "Return periods are assumed, and damage curves are not calibrated to Kenyan claims.",
    ]
    if rec["run"] == "enhanced":
        trust.append(
            "The figures include the AI hazard adjustment (reviewed evidence or the drainage model), which raises losses "
            "where drainage problems are likely; compare with the baseline before relying on it."
        )
    if f["price_adequacy"] is not None and 0.9 <= f["price_adequacy"] < 1.1:
        trust.append(
            "The price sits close to technical, so small changes in the assumptions could change the verdict."
        )
    level = (
        "low"
        if (rec.get("origin") and "SYNTHETIC" in rec["origin"]) or (zero and zero >= 30)
        else "moderate"
    )
    return {
        "headline": headline,
        "outcome": rec["outcome"],
        "share_pct": share,
        "reasons": reasons[:4],
        "conditions": conditions,
        "trust_level": level,
        "trust": trust,
        "figures": {
            "Our premium": _kes(f["our_premium_kes"]),
            "Our expected annual loss": _kes(f["our_aal_kes"]),
            f"Our 1-in-{f['pml_return_period']:g} loss": _kes(f["our_pml_kes"]),
            "Price adequacy": f"{f['price_adequacy']:.0%}"
            if f["price_adequacy"] is not None
            else "not testable",
        },
        "note": "Advice from fixed rules on the model output. A person makes and records the decision.",
    }
