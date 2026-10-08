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
# Form starting values: the submitted offer, else what the submission document states. Pre-filling never counts as
# submitting: `offer` stays empty until "Get recommendation" is pressed.
defaults = dict(offer)
prefilled = False
review = st.session_state.get("submission_review") or {}
if not offer and review.get("analysis") and review.get("label") == st.session_state.get("run_label"):
    # The submission document states the premium and the share on offer: start from them.
    from floodcat.ai.document_analysis import term_value

    pts = review["analysis"]["data_points"]
    doc_premium = term_value(pts, "premium_100")
    doc_share = term_value(pts, "accepted_share_pct") or term_value(pts, "placed_share_pct")
    if doc_premium:
        defaults = {"premium": doc_premium, **({"share": doc_share} if doc_share else {})}
        prefilled = True
with st.form("offer"):
    section("The offer", "Premium for 100% of the risk, and the share you are offered.")
    if prefilled:
        st.caption("Pre-filled from the submission document (premium for 100% and the accepted share); check before submitting.")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        premium = st.number_input(
            "Offered premium for 100% (KES)",
            min_value=0.0,
            value=float(defaults.get("premium", 0.0)),
            step=100_000.0,
            format="%.0f",
        )
        share = st.number_input(
            "Offered share (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(defaults.get("share", 10.0)),
            step=0.5,
        )
        run = (
            st.segmented_control(
                "Hazard",
                runs,
                default=defaults.get("run", runs[0]),
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
                default=defaults.get("basis", "insured"),
                format_func={"gross": "Ground-up loss", "insured": "Gross loss (after deductible & limit)"}.get,
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
        with state.platform().tx() as conn:
            book, written = data.written_book(
                conn,
                p,
                rules["pml_return_period"],
                exclude_run_id=report["analysis_id"],
            )
        rec = recommend(
            report,
            offer["premium"],
            offer["share"],
            rules,
            run=offer["run"],
            basis=offer["basis"],
            book=book,
            book_written=written,
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

    from floodcat.underwriting.advice import advise
    from floodcat.underwriting.pricing import breakdown

    pricing = breakdown(rec)
    advice = advise(rec, pricing, report)
    acc = rec["accumulation"]

    # Our advice -----------------------------------------------------------------------------------------------
    with st.container(border=True):
        section("Our advice")
        st.markdown(f"**{advice['headline']}**")
        a_col, b_col = st.columns(2, gap="large")
        with a_col:
            st.markdown("**Why**")
            st.markdown("\n".join(f"- {r}" for r in advice["reasons"]))
        with b_col:
            st.markdown(
                "**Write it only if**"
                if advice["outcome"] != "decline"
                else "**Before reconsidering**"
            )
            st.markdown(
                "\n".join(f"- {c}" for c in advice["conditions"])
                or "- No further conditions from the model."
            )
        with st.expander(
            f"How far to trust this: {advice['trust_level']}", icon=":material/balance:"
        ):
            st.markdown("\n".join(f"- {t}" for t in advice["trust"]))
        st.caption(advice["note"])

    # Pricing and premium adequacy ----------------------------------------------------------------------------
    left, right = st.columns(2, gap="large")
    with left.container(border=True, height="stretch"):
        section("Pricing and premium adequacy", "For 100% of the risk")
        verdict_colour = {
            "adequate": "green",
            "thin": "orange",
            "inadequate": "red",
            "untested": "gray",
        }[pricing["verdict"]]
        st.markdown(
            f":{verdict_colour}-badge[{pricing['verdict'].capitalize()}] {pricing['verdict_text']}"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Technical premium build-up": x["step"],
                        "KES": state.kes(x["amount_kes"], compact=False),
                    }
                    for x in pricing["steps"]
                ]
                + [
                    {
                        "Technical premium build-up": "Offered premium",
                        "KES": state.kes(pricing["offered_kes"], compact=False),
                    },
                    {
                        "Technical premium build-up": "Shortfall against technical",
                        "KES": state.kes(pricing["shortfall_kes"], compact=False),
                    },
                    {
                        "Technical premium build-up": f"Lowest premium the rules accept ({rules['decline_below_adequacy']:.0%} of technical)",
                        "KES": state.kes(
                            pricing["minimum_acceptable_kes"], compact=False
                        ),
                    },
                ]
            ),
            hide_index=True,
            width="stretch",
            alt="Technical premium build-up and offered premium",
        )
        m = lambda v, fmt: fmt.format(v) if v is not None else "—"
        kpis(
            [
                (
                    "Rate per mille",
                    m(pricing["rate_per_mille_offered"], "{:.2f}‰"),
                    "Offered premium per KES 1,000 of insured value",
                    f"technical {m(pricing['rate_per_mille_technical'], '{:.2f}‰')}",
                ),
                (
                    f"Rate on line",
                    m(pricing["rate_on_line_pct"], "{:.1f}%"),
                    f"Offered premium ÷ 1-in-{pricing['pml_return_period']:g} loss",
                ),
                (
                    "Payback",
                    m(pricing["payback_years"], "{:.0f} yrs"),
                    f"Years of premium to pay one 1-in-{pricing['pml_return_period']:g} loss",
                ),
            ],
            columns=3,
        )
        explain(
            "How the technical premium is built from the modelled annual loss, and how the offered premium compares.",
            f"Adequacy = offered ÷ technical. From 100% the price is adequate; between {rules['decline_below_adequacy']:.0%} and 100% it is thin and the "
            f"rules cut the line; below {rules['decline_below_adequacy']:.0%} they decline. Rate measures are for comparison, not market benchmarks.",
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
            f"Our share of the 1-in-{f['pml_return_period']:g} loss must stay within {state.kes(rules['max_pml_kes'])}, of insured value within "
            f"{state.kes(rules['max_line_tiv_kes'])}, and in any 1 km area (with our book) within {state.kes(rules['max_area_pml_kes'])}. "
            f"Shares are rounded down to {rules['share_step_pct']:g}%; below {rules['min_share_pct']:g}% the rules decline.",
            ["ASSUMPTION"],
        )

    # Accumulation --------------------------------------------------------------------------------------------
    with st.container(border=True):
        section(
            "Accumulation",
            f"Loss at 1-in-{acc['pml_return_period']:g} by 1 km area: this risk at the recommended share plus what we have already written",
        )
        if not acc.get("available", True):
            st.caption(
                "This analysis has no per-property results, so accumulation cannot be checked."
            )
        else:
            for w in acc["warnings"]:
                if w["level"] == "limit":
                    st.error(w["text"], icon=":material/crisis_alert:")
                elif w["level"] == "warning":
                    st.warning(w["text"], icon=":material/warning:")
            if not any(w["level"] in ("limit", "warning") for w in acc["warnings"]):
                st.success(
                    f"No 1 km area goes over the limit of {state.kes(acc['limit_kes'])}, and no area holds more than "
                    f"{rules['max_area_tiv_pct']:g}% of this risk's value.",
                    icon=":material/check_circle:",
                )
            st.caption(
                f"Our book: {acc['book_risks']} written risk(s) recorded with an accept or smaller-share decision."
                if acc["book_risks"]
                else "Our book: no written risks recorded yet, so only this risk is counted."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Area": a["area"],
                            "Properties": a["properties"],
                            "Share of value": a["tiv_share_pct"] / 100,
                            "This risk, 100%": state.kes(a["loss_100_kes"]),
                            "Ours at recommended share": state.kes(a["our_loss_kes"]),
                            "Already held": state.kes(a["book_loss_kes"]),
                            "Total held": state.kes(a["combined_loss_kes"]),
                            "Status": "Over limit"
                            if a["over_limit"]
                            else (
                                "Concentrated" if a["concentrated"] else "Within limit"
                            ),
                        }
                        for a in acc["areas"][:12]
                    ]
                ),
                hide_index=True,
                width="stretch",
                alt="Accumulation by area",
                column_config={
                    "Share of value": st.column_config.ProgressColumn(
                        format="percent", min_value=0, max_value=1
                    )
                },
            )
            explain(
                "Where this risk's flood loss would fall, next to what the organisation already holds in the same place.",
                "Each row is a 1 km area named after the nearest county flood area. A large total in one area means one local flood hits "
                "many policies at once. Areas are not independent events: one storm can reach several.",
                ["PROXY", "ASSUMPTION", *rec["origin"]],
                source="property losses at the PML return period · recorded underwriting decisions · your organisation’s rules",
            )

    with st.expander("Every rule check", icon=":material/checklist:"):
        STATUS = {
            "pass": "Pass",
            "warn": "Warning",
            "limit": "Limits the share",
            "fail": "Fails",
        }
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
