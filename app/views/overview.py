"""Overview: the answer first (one sentence, five numbers), then the curve and who pays; detail behind one switch."""

from decimal import Decimal
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.reporting.terms import waterfall
from ui import glance, state
from ui.charts import donut, hbars, split_bar, ylt_chart
from ui.components import explain, page_header, require_result, run_banner, section
from ui.corrections_view import results_panel

page_header("Overview")
report = require_result()
glance.style()
run_banner(report)
results_panel(report)
cfg = state.config()
corrected = "enhanced" in report["runs"]
# With a correction switched on, every figure on this page is the corrected run; the baseline stays on the curve.
run = report["runs"]["enhanced" if corrected else "baseline"]
curve = {p["return_period_years"]: p for p in run["ep_curve"]}
rarest_rp = max(curve)
tier_100 = state.tier_for_rp(cfg, 100.0) if 100.0 in curve else run["ep_curve"][-2]["tier"]
rp_100 = cfg.return_periods[tier_100]
rarest = state.tier_for_rp(cfg, rarest_rp)
p100 = curve[rp_100]
flagged = sum(1 for r in run["property_losses"][rarest] if r["hazard_score"] > 0)
steps = {k: v for k, _, v in waterfall(run, tier_100)}
owners = -(steps["deductible"] + steps["limit"])
reinsurers = -(steps["quota_share"] + steps["cat_xl"])

# 1 · The answer --------------------------------------------------------------------------------------------------
glance.answer(
    f"In a <b>1-in-{rp_100:g}</b> flood this portfolio loses <b>{state.kes(p100['loss_kes'])}</b> "
    f"({state.pct(p100['loss_pct_of_tiv'])} of its value). Over the long run it loses <b>{state.kes(run['aal']['aal_kes'])}</b> a year."
    + (f" After deductibles and reinsurance the insurer keeps <b>{state.kes(steps['net'])}</b> of that 1-in-{rp_100:g} loss."
       if "reinsurance" in run else "")
)
if corrected:
    base = report["runs"]["baseline"]
    base_curve = {p["return_period_years"]: p for p in base["ep_curve"]}
    st.caption(
        f"Corrected for places the terrain map misses (AI / PROXY). Without the correction: 1-in-{rp_100:g} loss "
        f"{state.kes(base_curve[rp_100]['loss_kes'])}, average a year {state.kes(base['aal']['aal_kes'])}. "
        f"{report['ai_contribution']['changed_properties']} properties' hazard raised. A higher loss is not proof of a better model."
    )
glance.tiles([
    ("🏠", "Insured value", state.kes(report["modelled_tiv_kes"]), f"{report['modelled_count']} properties", ""),
    ("🌊", f"1-in-{rp_100:g} loss", state.kes(p100["loss_kes"]), f"{state.pct(p100['loss_pct_of_tiv'])} of value · 1% a year", "blue"),
    ("🌪️", f"1-in-{rarest_rp:g} loss", state.kes(curve[rarest_rp]["loss_kes"]),
     f"{state.pct(curve[rarest_rp]['loss_pct_of_tiv'])} of value · 0.4% a year", "orange"),
    ("📅", "Average a year", state.kes(run["aal"]["aal_kes"]), "long-run expected loss", "green"),
    ("📍", "Properties at risk", f"{flagged} of {report['modelled_count']}", "flagged by the hazard map", "red" if flagged else ""),
])
glance.chips([
    (f"depth = score × {cfg.max_depth_m:g} m", "The hazard map gives a 0–1 score, not a depth. We read a score of 1 as "
     f"{cfg.max_depth_m:g} m of water — our judgement, and the biggest lever on every loss."),
    (f"1-in-{rp_100:g} = “{tier_100}” tier", "The five hazard tiers have no years attached; we assume 10, 25, 50, 100 and 250 years. "
     "The narrowest footprint (“extreme”) is the most frequent flood."),
    ("JRC curves, adapted per class", "Published JRC Africa residential depth–damage curve, stretched per construction class "
     "and capped at 80–95%. Not calibrated to Kenyan claims."),
], key="overview")
show = glance.details("overview")

# 2 · Curve and who pays -----------------------------------------------------------------------------------------
left, right = st.columns([3, 2], gap="large")
with left:
    section("Loss vs flood rarity")
    try:
        st.altair_chart(ylt_chart(state.ylt(report), report, compare_ai=report["ai_contribution"]["enabled"]),
                        width="stretch")
        explain(
            "Portfolio loss against how rare the year’s worst flood is (10,000 simulated years); diamonds are the five scenarios.",
            "Read across from a return period: “1-in-100” ≈ 1% chance in any year of a loss at least this large.",
            ["PROXY", "ASSUMPTION", *state.exposure_labels(report)],
        )
    except ModelError as exc:
        st.warning(str(exc))
with right:
    section(f"Who pays in a 1-in-{rp_100:g} flood")
    st.altair_chart(split_bar(run, tier_100), width="stretch")
    glance.tiles([
        ("🧾", "Owners", state.kes(owners), "deductible + above limit", ""),
        ("🤝", "Reinsurers", state.kes(reinsurers), "quota share + cat XL", "orange"),
        ("🏦", "Insurer keeps", state.kes(steps["net"]), "net loss", "blue"),
    ])
    glance.formula("Net = Ground-up − Deductible − Reinsurance",
                   f"{state.kes(steps['ground_up'])} − {state.kes(owners)} − {state.kes(reinsurers)} = {state.kes(steps['net'])}")

# 3 · What and where ---------------------------------------------------------------------------------------------
c1, c2 = st.columns(2, gap="large")
with c1:
    section("What loses", f"1-in-{rp_100:g} loss by construction")
    items = run["breakdowns"][tier_100]["construction"]
    chart = donut([{"Class": state.class_label(i["id"]), "Loss": float(Decimal(i["loss_kes"])), "Amount": state.kes(i["loss_kes"])}
                   for i in items], "Class", "Loss", fmt="Amount")
    st.altair_chart(chart, width="stretch") if chart else st.caption("No modelled loss.")
with c2:
    section("Where it concentrates", f"Share of the 1-in-{rp_100:g} loss")
    areas = run["breakdowns"][tier_100].get("hotspot_area", [])
    rows = [{"Area": a["id"] if not a["id"].startswith("no named") else "Away from named areas",
             "Share (%)": round(a["loss_share_pct"], 1), "Loss": state.kes(a["loss_kes"]), "_label": f"{a['loss_share_pct']:.0f}%"}
            for a in areas[:5]]
    chart = hbars(rows, "Area", "Share (%)", "Share of loss (%)", text="_label")
    if chart:
        st.altair_chart(chart, width="stretch")
    if st.button("Open the map", icon=":material/map:"):
        st.switch_page("views/map.py")

# 4 · Things to act on, in one line each -------------------------------------------------------------------------
hints = (report.get("drainage_hints") or {}).get("properties", [])
review = st.session_state.get("submission_review")
doc_review = review if review and review.get("label") == st.session_state.get("run_label") else None
nudges = st.container(horizontal=True, gap="small")
if hints:
    nudges.warning(f"💧 {len(hints)} propert{'y' if len(hints) == 1 else 'ies'} near a named flood area that the map scores low — "
                   "consider drainage evidence (losses unchanged).")
if doc_review:
    warn = [c for p in doc_review["properties"] for c in p["checks"] if c["severity"] in ("error", "warning")]
    nudges.info(f"📄 Submission document: {len(warn)} point(s) to check — switch on Show details.")
ai_row = st.container(horizontal=True, gap="small")
if ai_row.button("Draft AI briefing", icon=":material/auto_awesome:", key="ov_brief"):
    st.session_state["ov_show_brief"] = True
with ai_row.popover("Ask Xpat", icon=":material/chat:"):
    from ui.chat_view import chat_panel

    chat_panel("overview_assistant", report=report)
if ai_row.button("Underwriting decision", icon=":material/gavel:", key="ov_decide"):
    st.switch_page("views/decision.py")
if hints and ai_row.button("Drainage evidence", icon=":material/water_drop:", key="overview_hint"):
    st.switch_page("views/evidence.py")
if st.session_state.get("ov_show_brief"):
    from ui.briefing_view import briefing_panel

    with st.container(border=True):
        section("AI underwriting briefing")
        briefing_panel()

# 5 · Detail on demand ---------------------------------------------------------------------------------------------
if show:
    from ui.financial_view import financial_terms_panel

    financial_terms_panel(report, "overview_terms")
    section("Largest losses", f"1-in-{rarest_rp:g}")
    top = run["breakdowns"][rarest]["top_properties"][:8]
    chart = hbars([{"Property": p["loc_id"], "Loss (KES m)": round(float(Decimal(p["loss_kes"])) / 1e6, 1),
                    "Class": state.class_label(p["housing_class"]), "_label": state.kes(p["loss_kes"])} for p in top],
                  "Property", "Loss (KES m)", "Loss (KES m)", text="_label", color="#eb6834")
    if chart:
        st.altair_chart(chart, width="stretch")
    ai = report["ai_contribution"]
    st.caption(f"AI flood evidence: {ai['changed_properties']} properties raised, average annual loss {state.kes(ai['aal_delta_kes'])} higher."
               if ai["enabled"] else "AI flood evidence: none applied to this run (AI flood evidence page).")
    if doc_review and doc_review.get("analysis"):
        from ui.document_view import document_analysis_panel

        document_analysis_panel(doc_review["analysis"], report=report, key="overview_doc")
