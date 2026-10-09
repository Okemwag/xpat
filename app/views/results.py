import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from ui import glance, state
from ui.charts import BASIS_LABEL, class_bars, scenario_source, who_pays_chart, ylt_chart
from ui.charts import hbars
from ui.components import (
    badges,
    explain,
    kpis,
    page_header,
    pipeline_strip,
    require_result,
    run_banner,
    section,
    tier_selector,
)

page_header("Loss curve")
pipeline_strip("Loss curve")
report = require_result()
glance.style()
run_banner(report)
cfg = state.config()
runs = ["baseline"] + (["enhanced"] if "enhanced" in report["runs"] else [])
run = "baseline"
basis = "gross"
with st.container(horizontal=True, vertical_alignment="bottom"):
    if len(runs) > 1:
        run = (
            st.segmented_control(
                "Model",
                runs,
                default="baseline",
                format_func={
                    "baseline": "Baseline",
                    "enhanced": "With AI evidence",
                }.get,
            )
            or "baseline"
        )
    bases = ["gross"] + (["insured"] if "insured" in report["runs"][run] else []) + (
        ["ceded", "net"] if "reinsurance" in report["runs"][run] else []
    )
    if len(bases) > 1:
        basis = (
            st.segmented_control(
                "Loss basis",
                bases,
                default="insured" if "insured" in bases else "gross",
                format_func=BASIS_LABEL.get,
            )
            or bases[0]
        )
try:
    with st.spinner("Simulating 10,000 years…"):
        curves = state.ylt(report)
except ModelError as exc:
    st.error(str(exc))
    st.stop()
sim = curves[run].get(basis) or curves[run]["gross"]
low, high = sim["band_pct"]
rarest = sim["rarest_modelled_return_period"]

table = {int(p["return_period_years"]): p for p in sim["table"]}


TONES = {10: "", 100: "blue", 250: "orange", 1000: "red"}


def tile(rp):
    p = table.get(rp)
    return (
        ("🌊", f"1-in-{rp:,} loss", state.kes(p["loss_kes"]),
         f"{1 / rp:.1%} a year · range {state.kes(p['band_low_kes'])}–{state.kes(p['band_high_kes'])}", TONES[rp])
        if p else None
    )


p100 = table.get(100)
if p100:
    glance.answer(
        f"Each year there is about a <b>1% chance</b> of a {BASIS_LABEL[basis].lower()} loss of "
        f"<b>{state.kes(p100['loss_kes'])}</b> or more; on average the portfolio loses <b>{state.kes(sim['aal']['aal_kes'])}</b> a year."
    )
glance.tiles([
    tile(10), tile(100), tile(250), tile(1000),
    ("📅", "Average a year", state.kes(sim["aal"]["aal_kes"]),
     f"range {state.kes(sim['aal']['band_low_kes'])}–{state.kes(sim['aal']['band_high_kes'])}", "green"),
])
f1, f2 = st.columns(2, gap="medium")
with f1:
    glance.formula("Annual chance = 1 ÷ return period", "1-in-100 → 1 ÷ 100 = 1% a year",
                   "Not “once every 100 years”: two 1-in-100 floods can come in a row.")
with f2:
    glance.formula(f"AAL = Σ year losses ÷ {sim['years']:,} years",
                   f"= {state.kes(sim['aal']['aal_kes'])} a year",
                   f"{sim['zero_loss_years']:,} of the {sim['years']:,} simulated years have no loss.")
glance.chips([
    ("tiers = 10 / 25 / 50 / 100 / 250 yr", "The hazard tiers have no years attached; this mapping is our assumption, from the "
     "reference dashboard. The narrowest footprint (“extreme”) is the most frequent flood."),
    (f"beyond 1-in-{rarest:g}: no rarer floods", f"Right of 1-in-{rarest:g} the curve varies only with damage uncertainty; "
     "no bigger floods are modelled."),
], key="results")

with st.container(border=True):
    st.altair_chart(
        ylt_chart(curves, report, compare_ai=len(runs) > 1, basis=basis),
        width="stretch",
    )
    explain(
        f"{BASIS_LABEL[basis]} loss reached or exceeded by a year’s worst flood, 1-in-1 to 1-in-10,000 years; diamonds = the five hazard scenarios; "
        f"grey band = {low:g}th–{high:g}th percentile of re-sampled years.",
        f"“1-in-100” ≈ 1% chance in any year. Right of the dashed line (1-in-{rarest:g}) only damage uncertainty varies.",
        ["PROXY", "ASSUMPTION", *state.exposure_labels(report)],
        source=f"hazard tiers · assumed return periods · adapted JRC curves · {state.exposure_words(report)}",
    )

with st.expander("Loss table", icon=":material/table:"):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Rarity": f"1-in-{p['return_period_years']:,.0f}",
                    "Annual chance": f"{p['annual_exceedance_probability']:.2%}",
                    "Loss": state.kes(p["loss_kes"], compact=False),
                    f"Range ({low:g}–{high:g}th pct)": f"{state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])}",
                    "Modelled from": "hazard tiers"
                    if p["return_period_years"] <= rarest
                    else "damage uncertainty only",
                }
                for p in sim["table"]
            ]
        ),
        hide_index=True,
        width="stretch",
    )
with st.expander(
    "The five scenarios and their damage-uncertainty ranges",
    icon=":material/stacked_bar_chart:",
):
    source = scenario_source(report, run, basis)
    try:
        damage = state.uncertainty(report)[run].get(basis)
    except ModelError:
        damage = None
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Tier": p["tier"],
                    "Assumed rarity": state.rp_label(p["return_period_years"]),
                    "Loss": state.kes(p["loss_kes"], compact=False),
                    "% of value": state.pct(p["loss_pct_of_tiv"]),
                    **(
                        {
                            "If damage curves are uncertain": f"{state.kes(damage['by_tier'][p['tier']]['p_low_kes'])} – {state.kes(damage['by_tier'][p['tier']]['p_high_kes'])}"
                        }
                        if damage
                        else {}
                    ),
                }
                for p in source["ep_curve"]
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Tier names describe how extreme a map cell is, not how often it floods: “extreme” is the most frequent event, “common” the rarest."
    )
# Who pays ---------------------------------------------------------------------------------------------------
r_run = report["runs"][run]
if "insured" in r_run or "reinsurance" in r_run:
    section("Who pays in each scenario", "Ground-up loss split into deductible, above the limit, quota share, catastrophe excess of loss and net loss")
    left, right = st.columns([3, 2], gap="large")
    with left.container(border=True, height="stretch"):
        st.altair_chart(who_pays_chart(report, run), width="stretch")
        explain(
            "Each bar is the ground-up loss in one scenario. Owners bear the deductible and anything above the limit; the rest is "
            "the gross loss, which the quota share and the catastrophe excess of loss reduce to the net loss.",
            "As floods get rarer the catastrophe excess of loss takes over: above its threshold the net loss stops growing until "
            "the layer's maximum is used up.",
            ["ASSUMPTION", *state.exposure_labels(report)],
            source="policy terms and reinsurance programme on the Assumptions page ·",
        )
    with right.container(border=True, height="stretch"):
        rows = []
        if "insured" in r_run:
            t = r_run["insured"]["terms"]
            rows.append(("Deductible · limit", f"{t['deductible_pct_of_tiv']:.1%} · {t['limit_pct_of_tiv']:.0%} of each property's value (or each row's own terms)"))
        if "reinsurance" in r_run:
            ri = r_run["reinsurance"]
            stc = ri["structure"]
            rows += [
                ("Quota share", f"the reinsurer pays {stc['quota_share_cession']:.0%} of every {BASIS_LABEL[ri['basis']].lower()}"),
                ("Catastrophe excess of loss", f"pays above {state.kes(stc['xol_retention_kes'])} per catastrophe, up to {state.kes(stc['xol_limit_kes'])}, on the insurer's share"),
                ("Layer used up at", f"{state.kes(stc['xol_exhaustion_kes'])} {BASIS_LABEL[ri['basis']].lower()}"),
            ]
            kpis(
                [
                    ("Reinsurance recoveries AAL", state.kes(ri["ceded"]["aal"]["aal_kes"]), "Quota share + catastrophe excess of loss, per year"),
                    ("Net loss AAL", state.kes(ri["net"]["aal"]["aal_kes"]), "What the insurer keeps, per year"),
                ],
                columns=2,
            )
        for k, v in rows:
            st.markdown(f"**{k}:** {v}")
        st.caption(
            "Illustrative programme (ASSUMPTION), not a real treaty. No reinstatements, aggregate covers or second events in a year."
        )
    with st.expander("Split by scenario", icon=":material/table:"):
        gross = {p["tier"]: p for p in r_run["ep_curve"]}
        insured = {p["tier"]: p for p in r_run["insured"]["ep_curve"]} if "insured" in r_run else {}
        split = {t["tier"]: t for t in r_run["reinsurance"]["by_tier"]} if "reinsurance" in r_run else {}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rarity": state.rp_label(p["return_period_years"]),
                        "Ground-up loss": state.kes(p["loss_kes"]),
                        **({"Deductible": state.kes(r_run["insured"]["deductible_kes"][t]),
                            "Above the limit": state.kes(r_run["insured"]["above_limit_kes"][t]),
                            "Gross loss": state.kes(insured[t]["loss_kes"])} if insured and "deductible_kes" in r_run["insured"]
                           else {"Gross loss": state.kes(insured[t]["loss_kes"])} if insured else {}),
                        **(
                            {
                                "Quota share": state.kes(split[t]["quota_share"]),
                                "Catastrophe excess of loss": state.kes(split[t]["excess_of_loss"]),
                                "Net loss": state.kes(split[t]["net"]),
                            }
                            if split
                            else {}
                        ),
                    }
                    for t, p in gross.items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )

# Largest expected annual losses ------------------------------------------------------------------------------
if r_run.get("property_aal"):
    section("Largest expected annual losses", "Each property's own average annual loss; they add up to the portfolio's")
    top = r_run["property_aal"][:10]
    chart = hbars(
        [
            {
                "Property": p["loc_id"],
                "AAL (KES m)": round(float(p["aal_kes"]) / 1e6, 2),
                "Class": state.class_label(p["housing_class"]),
                "Insured value": state.kes(p["tiv_kes"]),
                "_label": state.kes(p["aal_kes"]),
            }
            for p in top
        ],
        "Property",
        "AAL (KES m)",
        "Average annual loss (KES m)",
        text="_label",
    )
    if chart:
        st.altair_chart(chart, width="stretch")
    st.caption(
        f"{len(r_run['property_aal'])} properties carry an expected annual loss; the rest are never flagged by the hazard map. "
        "Same integration as the portfolio AAL (no loss at 1-in-2 or more often, rarest loss held beyond 1-in-250)."
    )

section("By construction")
tier, rp = tier_selector("results_tier")
b = report["runs"][run]["breakdowns"][tier]
rows = [
    {
        "Class": state.class_label(i["id"]),
        "Loss (KES m)": round(float(i["loss_kes"]) / 1e6, 1),
        "Insured value": state.kes(i["tiv_kes"]),
        "Properties": i["property_count"],
        "_label": f"{i['loss_share_pct']:.0f}% · {state.kes(i['loss_kes'])}",
    }
    for i in b["construction"]
]
chart = hbars(
    rows, "Class", "Loss (KES m)", "Loss (KES m)", text="_label", height_per=40
)
if chart:
    st.altair_chart(chart, width="stretch")

with st.container(border=True):
    section("Ask the results")
    badges("AI")
    from ui.ask_view import ask_panel

    ask_panel(report, key="ask_results")
