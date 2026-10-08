import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from ui import state
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


def tile(rp):
    p = table.get(rp)
    return (
        (
            f"1-in-{rp:,}",
            state.kes(p["loss_kes"]),
            f"Simulation range {state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])}",
            f"{state.kes(p['band_low_kes'])}–{state.kes(p['band_high_kes'])}",
        )
        if p
        else None
    )


kpis(
    [
        tile(10),
        tile(100),
        tile(250),
        tile(1000),
        (
            "Average annual loss",
            state.kes(sim["aal"]["aal_kes"]),
            "Mean of the simulated years",
            f"{state.kes(sim['aal']['band_low_kes'])}–{state.kes(sim['aal']['band_high_kes'])}",
        ),
    ]
)

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
    section("Who pays", "The gross loss split between policyholders, the reinsurer and the insurer, per scenario")
    left, right = st.columns([3, 2], gap="large")
    with left.container(border=True, height="stretch"):
        st.altair_chart(who_pays_chart(report, run), width="stretch")
        explain(
            "Each bar is the gross loss in one scenario, split into what policyholders bear (deductibles and limits), "
            "what the reinsurer pays and what the insurer keeps.",
            "As floods get rarer the reinsurer's layer takes over: above the layer's start the insurer's share stops growing "
            "until the layer is used up.",
            ["ASSUMPTION", *state.exposure_labels(report)],
            source="policy terms and reinsurance programme on the Assumptions page ·",
        )
    with right.container(border=True, height="stretch"):
        rows = []
        if "insured" in r_run:
            t = r_run["insured"]["terms"]
            rows.append(("Policy terms", f"deductible {t['deductible_pct_of_tiv']:.1%}, limit {t['limit_pct_of_tiv']:.0%} of value per property (or each row's own terms)"))
        if "reinsurance" in r_run:
            ri = r_run["reinsurance"]
            stc = ri["structure"]
            rows += [
                ("Quota share", f"reinsurer takes {stc['quota_share_cession']:.0%} of every {ri['basis']} loss"),
                ("Excess of loss", f"{state.kes(stc['xol_limit_kes'])} xs {state.kes(stc['xol_retention_kes'])} per event, on the insurer's share"),
                ("Layer used up at", f"{state.kes(stc['xol_exhaustion_kes'])} {ri['basis']} loss"),
            ]
            kpis(
                [
                    ("Reinsurer AAL", state.kes(ri["ceded"]["aal"]["aal_kes"]), "Expected yearly cost to the reinsurer"),
                    ("Insurer keeps AAL", state.kes(ri["net"]["aal"]["aal_kes"]), "Expected yearly retained loss"),
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
                        "Gross": state.kes(p["loss_kes"]),
                        **({"Insured": state.kes(insured[t]["loss_kes"])} if insured else {}),
                        **(
                            {
                                "Quota share": state.kes(split[t]["quota_share"]),
                                "Excess of loss": state.kes(split[t]["excess_of_loss"]),
                                "Reinsurer total": state.kes(split[t]["ceded"]),
                                "Insurer keeps": state.kes(split[t]["net"]),
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
