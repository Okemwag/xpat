from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.platform import audit, data
from floodcat.underwriting.decision import OUTCOME_LABEL, RULE_SPEC, recommend
from ui import state
from ui.charts import AI, hbars
from ui.components import (
    badges,
    explain,
    kpis,
    page_header,
    require_result,
    run_banner,
    section,
    when,
)
from ui.reports_view import report_downloads

page_header(
    "Underwriting decision",
    "Enter the offered premium and share. Your organisation’s rules recommend accept, a smaller share or decline; "
    "AI can explain why; you make the call.",
)
report = require_result()
run_banner(report)
p = state.principal()
with state.platform().tx() as conn:
    rules = data.underwriting_rules(conn, p.org_id)
    authority = data.report_authority(conn, p, report)
    history = data.list_decisions(conn, p, run_id=report["analysis_id"])
names = state.people()
OUTCOME_STYLE = {
    "accept": ("green", ":material/check_circle:"),
    "share": ("orange", ":material/pie_chart:"),
    "decline": ("red", ":material/block:"),
}

# The offer ---------------------------------------------------------------------------------------------------
runs = ["enhanced", "baseline"] if "enhanced" in report["runs"] else ["baseline"]
offer = st.session_state.get("uw_offer", {})
if offer.get("analysis_id") != report["analysis_id"]:
    offer = {}
with st.form("offer"):
    section("The offer", "Premium for 100% of the risk, and the share you are offered.")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        premium = st.number_input(
            "Offered premium for 100% (KES)",
            min_value=0.0,
            value=float(offer.get("premium", 0.0)),
            step=100_000.0,
            format="%.0f",
        )
        share = st.number_input(
            "Offered share (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(offer.get("share", 10.0)),
            step=0.5,
        )
        run = (
            st.segmented_control(
                "Hazard",
                runs,
                default=offer.get("run", runs[0]),
                format_func={
                    "baseline": "Baseline map",
                    "enhanced": "With AI hazard adjustment",
                }.get,
            )
            if len(runs) > 1
            else runs[0]
        )
        basis = (
            st.segmented_control(
                "Loss basis",
                ["insured", "gross"],
                default=offer.get("basis", "insured"),
                format_func={"gross": "Gross", "insured": "Insured"}.get,
            )
            if "insured" in report["runs"]["baseline"]
            else "gross"
        )
    submitted = st.form_submit_button(
        "Get recommendation", type="primary", icon=":material/rule:"
    )
if submitted:
    offer = {
        "analysis_id": report["analysis_id"],
        "premium": premium,
        "share": share,
        "run": run or runs[0],
        "basis": basis or "gross",
    }
    st.session_state["uw_offer"] = offer
    st.session_state.pop("uw_rationale", None)

rec = None
if offer.get("premium"):
    try:
        rec = recommend(
            report,
            offer["premium"],
            offer["share"],
            rules,
            run=offer["run"],
            basis=offer["basis"],
        )
    except ModelError as exc:
        st.error(str(exc), icon=":material/error:")

if rec is None:
    if not offer.get("premium"):
        st.info(
            "Enter the offered premium and share to see what the rules recommend.",
            icon=":material/info:",
        )
else:
    f = rec["figures"]
    colour, icon = OUTCOME_STYLE[rec["outcome"]]
    with st.container(border=True):
        top = st.container(horizontal=True, vertical_alignment="center")
        top.markdown(
            f"### :{colour}[{icon} {OUTCOME_LABEL[rec['outcome']]}"
            + (
                f" — {rec['recommended_share_pct']:g}%]"
                if rec["outcome"] == "share"
                else "]"
            )
        )
        top.badge("rules recommendation", color="gray")
        if rec["binding_rules"]:
            st.caption("Decided by: " + ", ".join(rec["binding_rules"]) + ".")
        else:
            st.caption("Every rule passed at the offered share.")
        kpis(
            [
                (
                    "Recommended share",
                    f"{rec['recommended_share_pct']:g}%",
                    "Largest share all rules allow",
                    f"offered {rec['offered_share_pct']:g}%",
                ),
                (
                    "Price adequacy",
                    f"{f['price_adequacy']:.0%}"
                    if f["price_adequacy"] is not None
                    else "n/a",
                    "Offered premium ÷ technical premium (annual loss with an uncertainty load, at the target loss ratio)",
                ),
                (
                    "Expected loss ratio",
                    f"{f['expected_loss_ratio']:.0%}",
                    "Modelled annual loss ÷ offered premium",
                ),
                (
                    f"Our 1-in-{f['pml_return_period']:g} loss",
                    state.kes(f["our_pml_kes"]),
                    "At the recommended share",
                ),
                (
                    "Our premium",
                    state.kes(f["our_premium_kes"]),
                    "At the recommended share",
                ),
            ]
        )
        if authority:
            st.warning(
                "Above your organisation’s authority limits ("
                + "; ".join(authority)
                + "). "
                + (
                    "As head of underwriting you may decide."
                    if p.can("referrals.approve")
                    else "Only the head of underwriting can accept or take a share."
                ),
                icon=":material/gavel:",
            )
        if rec["origin"] != ["REAL"]:
            st.caption(
                "This analysis uses synthetic properties: the recommendation demonstrates the rules, it is not about a real risk."
            )

    left, right = st.columns(2, gap="large")
    with left.container(border=True, height="stretch"):
        section("Price", "Offered premium against the technical premium (100%)")
        chart = hbars(
            [
                {
                    "Premium": "Offered",
                    "KES m": round(float(Decimal(rec["premium_100_kes"])) / 1e6, 2),
                    "_label": state.kes(rec["premium_100_kes"]),
                },
                {
                    "Premium": "Technical",
                    "KES m": round(
                        float(Decimal(f["technical_premium_100_kes"])) / 1e6, 2
                    ),
                    "_label": state.kes(f["technical_premium_100_kes"]),
                },
                {
                    "Premium": "Modelled annual loss",
                    "KES m": round(float(Decimal(f["aal_100_kes"])) / 1e6, 2),
                    "_label": state.kes(f["aal_100_kes"]),
                },
            ],
            "Premium",
            "KES m",
            "KES m",
            text="_label",
            sort=None,
            height_per=40,
        )
        if chart:
            st.altair_chart(
                chart,
                width="stretch",
                alt="Offered premium, technical premium and modelled annual loss",
            )
        explain(
            "The offered premium next to the premium the rules need and the modelled annual loss.",
            f"Technical = annual loss × (1 + {rules['uncertainty_load']:.0%} load) ÷ {rules['target_loss_ratio']:.0%} target loss ratio. "
            f"Below {rules['decline_below_adequacy']:.0%} of technical the rules decline; between that and 100% they cut the line.",
            ["ASSUMPTION", "PROXY", *rec["origin"]],
            source=f"{rec['basis']} loss · {'AI-adjusted' if rec['run'] == 'enhanced' else 'baseline'} hazard · your organisation’s rules",
        )
    with right.container(border=True, height="stretch"):
        section("Share", "The largest share each rule allows; the shortest bar decides")
        chart = hbars(
            [
                {
                    "Rule": l["rule"],
                    "Share (%)": round(l["max_share_pct"], 1),
                    "_label": f"{l['max_share_pct']:.1f}%",
                }
                for l in rec["share_limits"]
            ],
            "Rule",
            "Share (%)",
            "Largest share allowed (%)",
            text="_label",
            sort=None,
            color=AI,
            height_per=40,
        )
        if chart:
            st.altair_chart(
                chart, width="stretch", alt="Largest share allowed by each rule"
            )
        explain(
            "Each capacity rule turned into the largest share it allows.",
            f"Our share of the 1-in-{f['pml_return_period']:g} loss must stay within {state.kes(rules['max_pml_kes'])}, and of insured value within "
            f"{state.kes(rules['max_line_tiv_kes'])}. Shares are rounded down to {rules['share_step_pct']:g}%; below {rules['min_share_pct']:g}% the rules decline.",
            ["ASSUMPTION"],
        )

    with st.expander("Every rule check", icon=":material/checklist:"):
        STATUS = {"pass": "✅ pass", "limit": "🟧 limits the share", "fail": "⛔ fails"}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rule": c["label"],
                        "Result": STATUS[c["status"]],
                        "Detail": c["detail"],
                    }
                    for c in rec["checks"]
                ]
            ),
            hide_index=True,
            width="stretch",
            alt="Rule checks",
            column_config={"Detail": st.column_config.TextColumn(width="large")},
        )

    # AI explanation ------------------------------------------------------------------------------------------
    with st.container(border=True):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown("#### Why — explained by AI")
        badges("AI")
        key = (
            report["analysis_id"],
            offer["premium"],
            offer["share"],
            offer["run"],
            offer["basis"],
            tuple(sorted(rules.items())),
        )
        held = st.session_state.get("uw_rationale")
        rationale = held[1] if held and held[0] == key else None
        if state.ai_enabled("extraction"):
            if st.button(
                "Explain this recommendation" if not rationale else "Explain again",
                icon=":material/auto_awesome:",
            ):
                from floodcat.ai.decision import explain as ai_explain

                if state.ai_quota():
                    try:
                        with st.spinner(
                            "Writing the explanation from the rule results…"
                        ):
                            rationale = ai_explain(
                                rec,
                                state.llm(
                                    client_data=state.run_has_client_data(report)
                                ),
                                report,
                            )
                        with state.platform().tx() as conn:
                            audit.record(
                                conn,
                                "ai.decision_explained",
                                actor=p,
                                target_type="run",
                                target_id=report["analysis_id"],
                                details={
                                    "model": rationale["model"],
                                    "prompt_version": rationale["prompt_version"],
                                    "outcome": rec["outcome"],
                                    "unsupported_figures": rationale[
                                        "unsupported_figures"
                                    ],
                                },
                                request=state.request_info(),
                            )
                        st.session_state["uw_rationale"] = (key, rationale)
                    except ModelError as exc:
                        st.error(str(exc), icon=":material/error:")
        else:
            st.caption(
                "AI is unavailable on this server or for your organisation. The rule checks above give the full reasoning."
            )
        if rationale:
            if rationale["unsupported_figures"]:
                st.warning(
                    "Not in the rule results: "
                    + ", ".join(rationale["unsupported_figures"])
                    + " — treat those figures with care.",
                    icon=":material/report:",
                )
            st.markdown(f"**{rationale['summary']}**")
            a, b = st.columns(2, gap="large")
            with a:
                st.markdown("**What drove it**")
                st.markdown("\n".join(f"- {x}" for x in rationale["drivers"]) or "—")
                st.markdown("**What would change it**")
                st.markdown(
                    "\n".join(f"- {x}" for x in rationale["what_would_change_it"])
                    or "—"
                )
            with b:
                st.markdown("**Ask the broker**")
                st.markdown(
                    "\n".join(f"- {x}" for x in rationale["questions_for_broker"])
                    or "—"
                )
                if rationale["trust"]:
                    st.markdown("**How far to trust it**")
                    st.write(rationale["trust"])
            with st.popover(
                f"{rationale['fact_count']} facts used", icon=":material/list:"
            ):
                for fact in rationale["facts"]:
                    st.markdown(f"- {fact['text']} · *{fact['provenance']}*")
            st.caption(
                f"AI-written by {rationale['model']} from the rule results. It cannot change the recommendation; you decide."
            )

    with st.container(border=True):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown("#### Referral note or quote letter — drafted by AI")
        badges("AI")
        from ui.memo_view import memo_panel

        memo_panel(rec, report, key)

    # The person's decision -----------------------------------------------------------------------------------
    if p.can("underwriting.decide"):
        with st.container(border=True):
            section(
                "Your decision",
                "Recorded with the rules’ recommendation, the AI explanation (if any) and your reason.",
            )
            choices = ["accept", "share", "decline"]
            outcome = (
                st.segmented_control(
                    "Decision",
                    choices,
                    default=rec["outcome"],
                    key=f"uw_outcome_{rec['outcome']}",
                    format_func={
                        "accept": "Accept offered share",
                        "share": "Take a smaller share",
                        "decline": "Decline",
                    }.get,
                )
                or rec["outcome"]
            )
            taken = None
            if outcome == "share":
                default = (
                    rec["recommended_share_pct"]
                    if 0 < rec["recommended_share_pct"] < rec["offered_share_pct"]
                    else rec["offered_share_pct"] / 2
                )
                taken = st.number_input(
                    "Share you will take (%)",
                    min_value=0.0,
                    max_value=float(rec["offered_share_pct"]),
                    value=float(default),
                    step=0.5,
                )
            differs = outcome != rec["outcome"] or (
                outcome == "share" and taken != rec["recommended_share_pct"]
            )
            reason = st.text_area(
                "Reason"
                + (
                    " (required — your decision differs from the rules)"
                    if differs
                    else " (optional)"
                ),
                max_chars=2000,
                placeholder="e.g. Broker confirmed the GPS points; price agreed after a 10% load.",
            )
            if st.button("Record decision", type="primary", icon=":material/gavel:"):
                result = state.guarded(
                    data.record_decision,
                    report["analysis_id"],
                    offer["premium"],
                    offer["share"],
                    outcome,
                    taken,
                    reason,
                    rationale,
                    run=offer["run"],
                    basis=offer["basis"],
                )
                if result is not state.FAILED:
                    st.toast("Decision recorded", icon=":material/check_circle:")
                    st.rerun()
    else:
        st.caption("Your role can see recommendations but not record decisions.")

# History, reports and rules ---------------------------------------------------------------------------------
if history:
    section("Decisions on this analysis")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "When": when(d["created_at"]),
                    "Who": names.get(d["decided_by"], "—"),
                    "Premium (100%)": state.kes(d["premium_100_kes"]),
                    "Offered": f"{float(d['offered_share_pct']):g}%",
                    "Rules said": OUTCOME_LABEL[d["recommendation"]["outcome"]]
                    + (
                        f" ({d['recommendation']['recommended_share_pct']:g}%)"
                        if d["recommendation"]["outcome"] == "share"
                        else ""
                    ),
                    "Decision": OUTCOME_LABEL[d["outcome"]]
                    + (
                        f" ({float(d['share_pct']):g}%)"
                        if d["outcome"] == "share"
                        else ""
                    ),
                    "Overrode": "yes" if d["overrode"] else "",
                    "AI explained": "yes" if d["rationale"] else "",
                    "Reason": d["reason"] or "",
                }
                for d in history
            ]
        ),
        hide_index=True,
        width="stretch",
        alt="Decisions recorded on this analysis",
    )
    sub_id = history[0]["submission_id"]
    if sub_id and p.can("submissions.manage"):
        with state.platform().tx() as conn:
            sub = data.get_submission(conn, p, sub_id)
        target = "declined" if history[0]["outcome"] == "decline" else "quoted"
        if target in data.TRANSITIONS[sub["status"]] and st.button(
            f"Move submission “{sub['name']}” to {target}", icon=":material/work:"
        ):
            if (
                state.guarded(
                    data.move_submission,
                    sub_id,
                    target,
                    f"Decision: {history[0]['outcome']}",
                )
                is not state.FAILED
            ):
                st.rerun()

with st.container(border=True):
    section("Reports", "The analysis with the decisions recorded on it")
    report_downloads(report, key="decision_reports")

with st.expander("Your organisation’s underwriting rules", icon=":material/tune:"):
    st.caption(
        "The rules are your organisation’s appetite (ASSUMPTION), not market guidance. Starter values come from configs/underwriting_rules.json."
        + (
            ""
            if p.can("underwriting.rules")
            else " Only the head of underwriting can change them."
        )
    )
    if p.can("underwriting.rules"):
        with st.form("rules"):
            edited = {}
            cols = st.columns(2)
            for i, (name, (low, high, meaning)) in enumerate(RULE_SPEC.items()):
                big = high >= 1e6
                edited[name] = cols[i % 2].number_input(
                    meaning,
                    min_value=float(low),
                    max_value=float(high),
                    value=float(rules[name]),
                    step=1e6 if big else 0.05 if high <= 5 else 1.0,
                    format="%.0f" if big else "%.2f",
                    key=f"rule_{name}",
                )
            if st.form_submit_button("Save rules", type="primary"):
                if (
                    state.guarded(data.set_underwriting_rules, edited)
                    is not state.FAILED
                ):
                    st.toast(
                        "Rules saved. New recommendations use them.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rule": RULE_SPEC[k][2],
                        "Value": f"{v:,.2f}".rstrip("0").rstrip("."),
                    }
                    for k, v in rules.items()
                ]
            ),
            hide_index=True,
            width="stretch",
            alt="Underwriting rules",
        )
