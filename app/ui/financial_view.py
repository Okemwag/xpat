"""From ground-up to net loss: the seven financial terms, defined, valued for a chosen scenario and drawn as a waterfall."""

import streamlit as st
from floodcat.reporting.terms import DEFINITION, NAME, waterfall
from . import state
from .charts import waterfall_chart
from .components import explain, section


def financial_terms_panel(report, key, run="baseline"):
    r = report["runs"][run]
    cfg = state.config()
    tiers = [p["tier"] for p in r["ep_curve"]]
    default = next((p["tier"] for p in r["ep_curve"] if p["return_period_years"] == 100.0), tiers[-1])
    section("From ground-up to net loss", "Who pays what in one flood, step by step")
    tier = st.segmented_control(
        "Scenario",
        tiers,
        default=default,
        format_func=lambda t: state.rp_label(cfg.return_periods[t]),
        key=f"{key}_tier",
        label_visibility="collapsed",
    ) or default
    steps = {k: v for k, _, v in waterfall(r, tier)}
    left, right = st.columns([3, 2], gap="large")
    with left.container(border=True, height="stretch"):
        st.altair_chart(waterfall_chart(report, tier, run), width="stretch")
        explain(
            f"The {state.rp_label(cfg.return_periods[tier])} flood: the ground-up loss, minus what owners bear (deductible, and "
            "anything above the limit), gives the gross loss; minus what reinsurers pay gives the net loss.",
            "Blue bars are totals; orange steps are the amounts taken off at each stage. Hover a bar for the amount.",
            ["ASSUMPTION", *state.exposure_labels(report)],
            source="policy terms and reinsurance programme on the Assumptions page ·",
        )
    terms = r.get("insured", {}).get("terms") or cfg.policy_terms
    ri = r.get("reinsurance", {}).get("structure")
    setting = {
        "deductible": f"{terms['deductible_pct_of_tiv']:.1%} of each property's value (or the row's own)",
        "limit": f"{terms['limit_pct_of_tiv']:.0%} of each property's value (or the row's own)",
        "quota_share": f"{ri['quota_share_cession']:.0%} of the gross loss" if ri else "off",
        "cat_xl": f"{state.kes(ri['xol_limit_kes'])} above {state.kes(ri['xol_retention_kes'])} per catastrophe, on the insurer's share"
        if ri else "off",
    }
    value = {
        "ground_up": steps["ground_up"],
        "deductible": -steps["deductible"],
        "limit": -steps["limit"],
        "gross": steps["gross"],
        "quota_share": -steps["quota_share"],
        "cat_xl": -steps["cat_xl"],
        "net": steps["net"],
    }
    with right.container(border=True, height="stretch"):
        for k in ("ground_up", "deductible", "limit", "gross", "quota_share", "cat_xl", "net"):
            amount = state.kes(value[k]) if k != "limit" else f"{state.kes(value[k])} above it"
            st.markdown(f"**{NAME[k]}** · {amount}")
            st.caption(DEFINITION[k] + (f" Here: {setting[k]}." if k in setting else ""))
