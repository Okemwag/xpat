"""Underwriting recommendation rules and the AI explanation (fake LLM; no network)."""

import pytest
from floodcat.ai.decision import build_facts, explain
from floodcat.core.errors import ModelError
from floodcat.underwriting.decision import (
    RULE_SPEC,
    default_rules,
    recommend,
    validate_rules,
)


def report(
    aal=1_000_000,
    pml=200_000_000,
    tiv=10_000_000_000,
    modelled=100,
    submitted=100,
    insured=None,
    enhanced=None,
):
    curve = [
        {"return_period_years": rp, "loss_kes": str(pml * f), "tier": t}
        for rp, f, t in (
            (10.0, 0.1, "extreme"),
            (25.0, 0.3, "severe"),
            (50.0, 0.5, "moderate"),
            (100.0, 0.8, "occasional"),
            (250.0, 1.0, "common"),
        )
    ]
    run = {"aal": {"aal_kes": str(aal)}, "ep_curve": curve}
    if insured:
        run["insured"] = {"aal": {"aal_kes": str(insured)}, "ep_curve": curve}
    runs = {"baseline": run}
    if enhanced:
        runs["enhanced"] = {"aal": {"aal_kes": str(enhanced)}, "ep_curve": curve}
    return {
        "runs": runs,
        "modelled_tiv_kes": str(tiv),
        "modelled_count": modelled,
        "input_count": submitted,
        "exposure_origin": {"labels": ["SYNTHETIC"]},
    }


RULES = {
    **default_rules(),
    "target_loss_ratio": 0.5,
    "uncertainty_load": 0.0,
    "decline_below_adequacy": 0.75,
    "marginal_share_factor": 0.5,
    "max_pml_kes": 50_000_000,
    "max_line_tiv_kes": 1e12,
    "min_share_pct": 5,
    "max_unmodelled_pct": 10,
    "share_step_pct": 0.5,
}


def test_starter_rules_load_and_are_complete():
    assert set(default_rules()) == set(RULE_SPEC)


def test_accept_when_price_and_capacity_are_within_rules():
    # technical = 1m / 0.5 = 2m; offered 2.5m → 125%; our PML at 10% = 20m ≤ 50m
    rec = recommend(report(), 2_500_000, 10, RULES)
    assert rec["outcome"] == "accept" and rec["recommended_share_pct"] == 10
    assert all(c["status"] == "pass" for c in rec["checks"])
    assert rec["figures"]["technical_premium_100_kes"] == "2000000" and rec["figures"][
        "price_adequacy"
    ] == pytest.approx(1.25)


def test_capacity_limits_the_share_and_rounds_down():
    # PML 200m; max 50m → 25%; offered 40% → share 25%
    rec = recommend(report(), 3_000_000, 40, RULES)
    assert rec["outcome"] == "share" and rec["recommended_share_pct"] == 25
    assert rec["binding_rules"] == ["Share of the 1-in-250 loss"]
    rec = recommend(report(pml=210_000_000), 3_000_000, 40, RULES)  # 23.8% → 23.5%
    assert rec["recommended_share_pct"] == 23.5


def test_thin_price_halves_the_line_and_low_price_declines():
    rec = recommend(report(), 1_800_000, 20, RULES)  # 90% of technical
    assert rec["outcome"] == "share" and rec["recommended_share_pct"] == 10
    rec = recommend(report(), 1_000_000, 20, RULES)  # 50% of technical
    assert rec["outcome"] == "decline" and rec["recommended_share_pct"] == 0
    assert next(c for c in rec["checks"] if c["code"] == "price")["status"] == "fail"


def test_too_many_unmodelled_records_declines():
    rec = recommend(report(modelled=80, submitted=100), 5_000_000, 10, RULES)
    assert (
        rec["outcome"] == "decline"
        and next(c for c in rec["checks"] if c["code"] == "data")["status"] == "fail"
    )


def test_share_below_the_minimum_declines():
    rec = recommend(
        report(pml=2_000_000_000), 5_000_000, 50, RULES
    )  # cap 2.5% < 5% minimum
    assert rec["outcome"] == "decline" and any(
        c["code"] == "min_share" for c in rec["checks"]
    )


def test_zero_modelled_loss_is_not_called_safe():
    rec = recommend(report(aal=0, pml=0), 1_000, 10, RULES)
    assert rec["outcome"] == "accept" and rec["figures"]["price_adequacy"] is None
    assert "not that they cannot flood" in rec["checks"][0]["detail"]


def test_insured_basis_and_ai_run_are_used_when_present():
    rec = recommend(report(insured=500_000), 2_000_000, 10, RULES)
    assert rec["basis"] == "insured" and rec["figures"]["aal_100_kes"] == "500000"
    rec = recommend(report(enhanced=3_000_000), 2_000_000, 10, RULES)
    assert (
        rec["run"] == "enhanced" and rec["outcome"] == "decline"
    )  # technical 6m → 33%
    assert (
        recommend(report(enhanced=3_000_000), 2_000_000, 10, RULES, run="baseline")[
            "outcome"
        ]
        == "accept"
    )


def test_pml_uses_nearest_rarer_scenario():
    rec = recommend(report(), 3_000_000, 10, {**RULES, "pml_return_period": 75})
    assert rec["figures"]["pml_return_period"] == 100.0


@pytest.mark.parametrize(
    "premium,share",
    [(0, 10), (-5, 10), ("abc", 10), (1000, 0), (1000, 101), (1000, float("nan"))],
)
def test_bad_offers_are_rejected(premium, share):
    with pytest.raises(ModelError):
        recommend(report(), premium, share, RULES)


@pytest.mark.parametrize(
    "change",
    [
        {"target_loss_ratio": 0},
        {"min_share_pct": 150},
        {"max_pml_kes": "lots"},
        {"extra_rule": 1},
    ],
)
def test_rules_are_validated(change):
    with pytest.raises(ModelError):
        validate_rules({**RULES, **change})
    with pytest.raises(ModelError):
        validate_rules({k: v for k, v in RULES.items() if k != "min_share_pct"})


class FakeLLM:
    model = "fake-gemini"

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate_json(self, system, prompt, schema):
        self.prompts.append(prompt)
        assert "outcome" not in schema["properties"] and "share" not in str(
            schema["properties"]
        )
        return self.response


def test_ai_explains_but_cannot_change_the_outcome_and_new_figures_are_flagged():
    rec = recommend(report(), 3_000_000, 40, RULES)
    llm = FakeLLM(
        {
            "summary": "The 1-in-250 loss limits the line to 25%. Rate it at 7.5% instead.",
            "drivers": ["Capacity, not price."],
            "what_would_change_it": ["A smaller offered share."],
            "trust": "Proxy hazard.",
            "questions_for_broker": ["Confirm GPS points."],
            "outcome": "accept",
        }
    )
    out = explain(rec, llm, report())
    assert out["unsupported_figures"] == ["7.5"]
    assert "outcome" not in out and rec["outcome"] == "share"
    assert "KES 200.0 m" in llm.prompts[0]  # the PML fact reached the prompt


def test_ai_explanation_rejects_empty_output():
    with pytest.raises(ModelError):
        explain(recommend(report(), 3_000_000, 10, RULES), FakeLLM({"summary": ""}))


def test_facts_cover_every_rule_check():
    rec = recommend(report(), 1_800_000, 20, RULES)
    facts = build_facts(rec)
    assert all(
        any(f"rule '{c['label']}'" in f["text"] for f in facts) for c in rec["checks"]
    )


def test_recommendation_on_the_real_pipeline(starter_rows):
    from floodcat.services.analysis import analyse

    r = analyse(starter_rows[:50])
    rec = recommend(r, 50_000_000, 20)
    assert rec["outcome"] in ("accept", "share", "decline")
    base = r["runs"]["baseline"]
    assert rec["basis"] == "insured"  # insured loss is on by default; the reinsurer prices what the policies pay
    assert float(rec["figures"]["aal_100_kes"]) == float(base["insured"]["aal"]["aal_kes"])
    assert float(recommend(r, 50_000_000, 20, basis="gross")["figures"]["aal_100_kes"]) == float(base["aal"]["aal_kes"])


def test_share_limits_show_which_rule_binds():
    rec = recommend(
        report(), 1_800_000, 40, RULES
    )  # price halves to 20%, PML allows 25%
    limits = {l["rule"]: l["max_share_pct"] for l in rec["share_limits"]}
    assert limits == {"Offered share": 40, "Price rule": 20, "1-in-250 loss limit": 25}
    assert rec["recommended_share_pct"] == min(limits.values())
