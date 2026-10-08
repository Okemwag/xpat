import json as _json
from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES, TIERS
from floodcat.core.errors import ModelError
from floodcat.platform import data
from floodcat.services.sensitivity import assumption_sensitivity
from floodcat.vulnerability.functions import damage_ratio, matrix
from ui import state
from ui.charts import (
    damage_vs_score_chart,
    scenario_lines,
    tornado,
    vulnerability_chart,
)
from ui.components import explain, kpis, page_header, pipeline_strip, section

page_header(
    "Assumptions & governance",
    "Every modelling choice is visible here. Change one, re-run, and see how much the answer moves.",
)
pipeline_strip("Vulnerability")
base = state.house_config()
current = state.config()
editable = state.can("assumptions.sandbox")
p = state.principal()
with state.platform().tx() as conn:
    house = data.house_set(conn, p.org_id)
    sets = data.list_sets(conn, p)
overrides = st.session_state.get("config_overrides") or {}
pending = [x for x in sets if x["status"] == "proposed"]
kpis(
    [
        (
            "House view",
            f"v{house['version']} {house['name']}" if house else "Xpat defaults",
            "Approved for your organisation" if house else "configs/default.json",
        ),
        (
            "Depth at score 1",
            f"{current.max_depth_m:g} m",
            "ASSUMPTION — results are sensitive to it",
        ),
        (
            "Return periods",
            " · ".join(f"{current.return_periods[t]:g}" for t in TIERS),
            "Years, extreme → common (ASSUMPTION)",
        ),
        (
            "Your sandbox",
            f"{len(overrides)} change(s)" if overrides else "none",
            "Personal; not the house view",
        ),
        ("Proposals waiting", len(pending), "Need a second person to approve"),
    ]
)
cfg = current

vuln_tab, sens_tab, change_tab, gov_tab = st.tabs(
    [
        ":material/home: Vulnerability",
        ":material/science: Sensitivity",
        ":material/tune: Change assumptions",
        ":material/account_balance: Governance",
    ]
)

# Vulnerability ----------------------------------------------------------------------------------------------
# Approximate damage at score 1 read from the reference dashboard in PROBLEM_STATEMENT.md, Figure 1 (display only).
REFERENCE_FIG1 = {
    "informal_iron_sheet": 0.85,
    "semi_permanent": 0.69,
    "permanent_masonry": 0.52,
    "concrete_rcc": 0.31,
}
with vuln_tab:
    left, right = st.columns([3, 2], gap="large")
    with left.container(border=True, height="stretch"):
        section(
            "Damage ratio against hazard score",
            "One curve per construction class (problem statement Figure 1)",
        )
        st.altair_chart(
            damage_vs_score_chart(cfg, REFERENCE_FIG1),
            width="stretch",
            alt="Damage ratio against hazard score by construction class",
        )
        explain(
            "The share of a building's rebuild value damaged at each hazard score, one curve per construction class. Crosses mark the reference "
            "dashboard's values at a score of 1 (problem statement, Figure 1).",
            f"Move right along a curve: higher score → deeper assumed water (score × {cfg.max_depth_m:g} m) → more damage. Fragile classes rise "
            "faster. Hover for “X% of rebuild value damaged”.",
            ["REAL", "ASSUMPTION"],
            source="JRC Africa residential curve (published) · class adjustments and max depth (ours) ·",
        )
    with right.container(border=True, height="stretch"):
        section("At a hazard score of 1", "Ours against the reference dashboard")
        compare = pd.DataFrame(
            [
                {
                    "Class": state.class_label(c),
                    "Reference": REFERENCE_FIG1[c],
                    "Xpat": damage_ratio(1.0, c, cfg),
                    "Cap": cfg.class_adjustments[c]["damage_cap"],
                }
                for c in CLASSES
            ]
        )
        st.dataframe(
            compare,
            hide_index=True,
            width="stretch",
            alt="Damage at score 1: reference, Xpat and cap by class",
            column_config={
                k: st.column_config.NumberColumn(format="percent")
                for k in ("Reference", "Xpat", "Cap")
            },
        )
        rcc_note = ""
        if state.result():
            items = {
                i["id"]: Decimal(i["tiv_kes"])
                for i in state.result()["runs"]["baseline"]["breakdowns"]["common"][
                    "construction"
                ]
            }
            rcc_share = items.get("concrete_rcc", Decimal(0)) / (
                sum(items.values()) or Decimal(1)
            )
            rcc_note = (
                f"In the current portfolio concrete holds {rcc_share:.0%} of insured value, so this choice "
                f"{'moves the portfolio loss more than any other vulnerability setting' if rcc_share > Decimal('0.5') else 'matters in proportion to that share'}"
                " — try a lower RCC depth scale under Change assumptions to see by how much."
            )
        with st.expander("Why our curves differ", icon=":material/help:"):
            st.markdown(f"""
- **Method.** The reference feeds the 0–1 score straight into a saturating curve. We convert score to an assumed depth
  (score × {cfg.max_depth_m:g} m) and read the published JRC Africa residential depth-damage curve, so the curve is sourced, not invented,
  and underwriters can reason in metres.
- **Fragile classes agree closely.** At a score of 1 we give informal iron-sheet {damage_ratio(1.0, "informal_iron_sheet", cfg):.0%} (reference ≈85%)
  and masonry {damage_ratio(1.0, "permanent_masonry", cfg):.0%} (≈52%).
- **Concrete is where we differ most:** {damage_ratio(1.0, "concrete_rcc", cfg):.0%} vs ≈31%. We scale the JRC depth axis by
  {cfg.class_adjustments["concrete_rcc"]["jrc_depth_scale"]:g} for RCC rather than imposing a low ceiling; the reference's 31% ceiling is itself a
  judgement call, below the brief's 80–95% cap guidance. {rcc_note}
- **Caps.** Our caps ({"/".join(f"{cfg.class_adjustments[c]['damage_cap']:.0%}" for c in CLASSES)}) follow the brief; at the base max depth
  they never bind, because {cfg.max_depth_m:g} m is too shallow to reach them.
""")
    left, right = st.columns([2, 3], gap="large")
    with left.container(border=True, height="stretch"):
        section("Damage against depth", "The JRC view, in metres")
        st.altair_chart(
            vulnerability_chart(cfg),
            width="stretch",
            alt="Damage ratio against assumed flood depth by construction class",
        )
        explain(
            "The same curves against assumed flood depth; the dashed line is the depth at a score of 1.",
            "Read up from a depth to the damage ratio for each class.",
            ["REAL", "ASSUMPTION"],
        )
    with right.container(border=True, height="stretch"):
        section(
            "Vulnerability matrix",
            "Damage ratio by hazard score and construction class",
        )
        m = matrix(cfg)
        st.dataframe(
            pd.DataFrame(
                {
                    "Hazard score": m["scores"],
                    "Assumed depth (m)": m["assumed_depth_m"],
                    **{state.class_label(c): m["damage_ratio"][c] for c in CLASSES},
                }
            ),
            hide_index=True,
            width="stretch",
            alt="Vulnerability matrix",
            column_config={
                state.class_label(c): st.column_config.NumberColumn(format="percent")
                for c in CLASSES
            },
        )
        st.caption(cfg.vulnerability_source)

# Sensitivity ------------------------------------------------------------------------------------------------
NAMES = {
    "base": "Current assumptions",
    "area_times_cost_tiv": "Insured value = area × cost/m²",
    "doubled_return_periods": "All return periods doubled",
}


def scenario_name(key):
    return NAMES.get(
        key,
        key.replace("max_depth_", "Depth at score 1 = ").replace("m", " m")
        if key.startswith("max_depth_")
        else key,
    )


with sens_tab:
    if not state.result():
        st.info(
            "Run a portfolio to see how its losses respond to each assumption.",
            icon=":material/info:",
        )
    else:
        st.write(
            "Re-runs the current portfolio under alternative assumptions, one at a time, to show which choices move the answer most."
        )
        if st.button(
            "Run sensitivity scenarios",
            icon=":material/science:",
            type="primary" if not st.session_state.get("sensitivity") else "secondary",
        ):
            with st.spinner("Re-running the portfolio under each scenario…"):
                rows, settings = (
                    st.session_state["rows"],
                    st.session_state.get("run_settings", {}),
                )
                from floodcat.exposure.validation import apply_declarations

                prepared, _ = apply_declarations(
                    rows,
                    settings.get("declare_synthetic", False),
                    settings.get("source_label"),
                    settings.get("assign_missing_ids", False),
                    settings.get("data_origin"),
                )
                st.session_state["sensitivity"] = {
                    "analysis_id": state.result()["analysis_id"],
                    "fingerprint": cfg.fingerprint,
                    **assumption_sensitivity(prepared, cfg, state.runtime().hazard),
                }
        sens = st.session_state.get("sensitivity")
        if sens and (
            sens.get("analysis_id") != state.result()["analysis_id"]
            or sens.get("fingerprint") != cfg.fingerprint
        ):
            st.caption(
                "These scenarios were run on a different analysis or different assumptions — run them again to refresh."
            )
        if sens:
            cases = sens["cases"]
            base_aal = Decimal(cases["base"]["aal_kes"])
            changes = [
                {
                    "Scenario": scenario_name(k),
                    "Change": float((Decimal(v["aal_kes"]) - base_aal) / base_aal * 100)
                    if base_aal
                    else 0.0,
                    "AAL": state.kes(v["aal_kes"]),
                }
                for k, v in cases.items()
                if k != "base"
            ]
            for c in changes:
                c["Abs"] = abs(c["Change"])
            biggest = max(changes, key=lambda c: c["Abs"]) if changes else None
            kpis(
                [
                    ("Average annual loss now", state.kes(base_aal)),
                    (
                        "Most influential choice",
                        biggest["Scenario"] if biggest else "—",
                        None,
                        f"{biggest['Change']:+.0f}% AAL" if biggest else None,
                    ),
                    ("Scenarios", len(changes), "One assumption changed at a time"),
                ]
            )
            left, right = st.columns(2, gap="large")
            with left.container(border=True, height="stretch"):
                section(
                    "How much each choice moves the annual loss",
                    "Change in average annual loss against the current assumptions",
                )
                chart = tornado(changes)
                if chart:
                    st.altair_chart(
                        chart,
                        width="stretch",
                        alt="Change in average annual loss under each assumption scenario",
                    )
                explain(
                    "Each bar re-runs the portfolio with one assumption changed and compares the average annual loss.",
                    "Longer bar = the answer depends more on that choice. Orange raises the loss, blue lowers it.",
                    ["ASSUMPTION", *state.exposure_labels()],
                )
            with right.container(border=True, height="stretch"):
                section("Loss curve under each scenario")
                lines = [
                    {
                        "Scenario": scenario_name(k),
                        "Return period (years)": cfg.return_periods[t]
                        * (2 if k == "doubled_return_periods" else 1),
                        "Loss (KES bn)": float(Decimal(v["loss_kes_by_tier"][t])) / 1e9,
                        "Loss": state.kes(v["loss_kes_by_tier"][t]),
                    }
                    for k, v in cases.items()
                    for t in TIERS
                ]
                chart = scenario_lines(lines, NAMES["base"])
                if chart:
                    st.altair_chart(
                        chart,
                        width="stretch",
                        alt="Loss against return period under each assumption scenario",
                    )
                explain(
                    "Portfolio loss in each hazard scenario, one line per assumption set; the thick blue line is the current assumptions.",
                    "Lines above the blue one give higher losses. Doubling return periods shifts the curve right without changing the losses.",
                    ["ASSUMPTION", *state.exposure_labels()],
                )
            with st.expander("Scenario table", icon=":material/table:"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Scenario": scenario_name(k),
                                **{
                                    state.rp_label(cfg.return_periods[t]): state.kes(
                                        v["loss_kes_by_tier"][t]
                                    )
                                    for t in TIERS
                                },
                                "Average annual loss": state.kes(v["aal_kes"]),
                            }
                            for k, v in cases.items()
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    alt="Loss by return period under each scenario",
                )
            for note in sens["notes"]:
                st.caption(note)
            st.caption("These are assumption scenarios, not confidence intervals.")

# Change assumptions (personal sandbox) ---------------------------------------------------------------------------
with change_tab:
    st.info(
        (
            f"House view: **{house['name']}** (version {house['version']}), approved for {state.org().get('name', 'your organisation')}."
            if house
            else "House view: Xpat's documented defaults (`configs/default.json`) — your organisation has not approved its own yet."
        )
        + (" You are working with **personal sandbox changes**." if overrides else ""),
        icon=":material/account_balance:",
    )
    if not editable:
        st.caption(
            "Your role can view the assumptions but not change them. Analysts and the head of underwriting can try changes and propose them."
        )
    with st.form("assumptions"):
        section("Hazard interpretation")
        max_depth = st.slider(
            "Depth at a hazard score of 1 (m)",
            0.5,
            4.0,
            float(current.max_depth_m),
            0.1,
            help="Pluvial flooding in Nairobi is typically 0.3–1.5 m; the brief's example uses 4 m.",
        )
        st.markdown(
            "**Assumed return period for each tier** (must increase from extreme to common)"
        )
        cols = st.columns(5)
        rps = {
            t: cols[i].number_input(
                t,
                min_value=1.0,
                max_value=10000.0,
                value=float(current.return_periods[t]),
                step=5.0,
                key=f"rp_{t}",
            )
            for i, t in enumerate(TIERS)
        }
        section(
            "Infrastructure deficit index",
            "Raises the hazard score where OpenStreetMap shows dense, mostly roofed ground — where rain runs off fast and "
            "drains are most often overwhelmed. It cannot see drains themselves. Off by default.",
        )
        imd = current.imd_index
        ready = state.imd_available()
        a, b = st.columns(2)
        imd_on = a.toggle(
            "Include the index",
            value=imd["enabled"] and ready,
            disabled=not ready,
            help=None if ready else "The index grid has not been built on this server (`make imd-index`).",
        )
        imd_weight = b.slider(
            "Strength (score added to dry ground at index 1, rarest tier)",
            0.0,
            1.0,
            float(imd["weight"]),
            0.05,
            help="At strength 0.4, fully dense ground with no terrain hazard gets a rarest-tier score of 0.4 (≈0.6 m at the default depth).",
        )
        section(
            "Vulnerability (per construction class)",
            "A lower depth scale means more damage at the same depth.",
        )
        adj = {}
        for c in CLASSES:
            l, a, b = st.columns([3, 2, 2])
            l.markdown(f"**{state.class_label(c)}**")
            adj[c] = {
                "jrc_depth_scale": a.number_input(
                    "JRC depth scale",
                    0.1,
                    3.0,
                    float(current.class_adjustments[c]["jrc_depth_scale"]),
                    0.05,
                    key=f"s_{c}",
                ),
                "damage_cap": b.slider(
                    "Damage cap",
                    0.80,
                    0.95,
                    float(current.class_adjustments[c]["damage_cap"]),
                    0.01,
                    key=f"c_{c}",
                ),
            }
        section("Annual loss & accumulation")
        a, b = st.columns(2)
        zero = a.number_input(
            "No loss below a 1-in-X event",
            1.0,
            9.9,
            float(current.aal_zero_loss_return_period),
            0.5,
        )
        radius = b.number_input(
            "Hotspot grouping radius (m)",
            250.0,
            10000.0,
            float(current.hotspot_tag_radius_m),
            250.0,
        )
        section(
            "Policy terms",
            "Per-property deductible and limit, giving an insured loss next to the gross loss. Rows with their own "
            "`deductible_kes` / `limit_kes` columns override these percentages.",
        )
        pt = current.policy_terms
        terms_on = st.toggle("Apply policy terms", value=pt["enabled"])
        a, b = st.columns(2)
        deductible = a.number_input(
            "Deductible (% of insured value)",
            0.0,
            50.0,
            pt["deductible_pct_of_tiv"] * 100,
            0.5,
        )
        limit = b.number_input(
            "Limit (% of insured value)", 1.0, 100.0, pt["limit_pct_of_tiv"] * 100, 5.0
        )
        section(
            "Reinsurance",
            "An illustrative programme: a quota share, then a per-event excess-of-loss layer on the insurer's share. "
            "Retention and limit are shares of the portfolio's insured value, so they scale to any upload.",
        )
        ri = current.reinsurance
        ri_on = st.toggle("Apply reinsurance", value=ri["enabled"])
        a, b, c = st.columns(3)
        cession = a.number_input("Quota share ceded (%)", 0.0, 95.0, ri["quota_share_cession"] * 100, 5.0)
        retention = b.number_input("Layer starts at (% of insured value)", 0.0, 50.0, ri["xol_retention_pct_of_tiv"] * 100, 0.25)
        layer = c.number_input("Layer size (% of insured value)", 0.0, 100.0, ri["xol_limit_pct_of_tiv"] * 100, 0.5,
                               help="0 = no excess-of-loss layer, quota share only.")
        section(
            "Uncertainty ranges",
            "Monte Carlo on the damage ratio only. σ is the spread of each property's damage around the curve; "
            "correlation is the share of that error common to the whole portfolio (a curve that is wrong everywhere).",
        )
        uc = current.uncertainty
        a, b, c = st.columns(3)
        sigma = a.slider(
            "Damage spread σ (log scale)", 0.0, 1.0, float(uc["damage_sigma"]), 0.05
        )
        rho = b.slider(
            "Portfolio-wide correlation ρ", 0.0, 1.0, float(uc["correlation"]), 0.05
        )
        trials = c.select_slider(
            "Simulations",
            [500, 1000, 2000, 5000, 10000],
            value=uc["trials"]
            if uc["trials"] in (500, 1000, 2000, 5000, 10000)
            else 2000,
        )
        apply = st.form_submit_button(
            "Apply to my sandbox and re-run",
            type="primary",
            icon=":material/refresh:",
            disabled=not editable,
        )
    if apply:
        new = {
            "max_depth_m": max_depth,
            "return_periods": rps,
            "class_adjustments": adj,
            "aal_zero_loss_return_period": zero,
            "hotspot_tag_radius_m": radius,
            "imd_index": {**imd, "enabled": imd_on, "weight": imd_weight},
            "reinsurance": {
                **ri,
                "enabled": ri_on,
                "quota_share_cession": cession / 100,
                "xol_retention_pct_of_tiv": retention / 100,
                "xol_limit_pct_of_tiv": layer / 100,
            },
            "policy_terms": {
                "enabled": terms_on,
                "deductible_pct_of_tiv": deductible / 100,
                "limit_pct_of_tiv": limit / 100,
            },
            "uncertainty": {
                **uc,
                "damage_sigma": sigma,
                "correlation": rho,
                "trials": trials,
            },
        }
        changed = {k: v for k, v in new.items() if v != getattr(base, k)}
        try:
            base.replace(**changed)
            st.session_state["config_overrides"] = changed
            if state.result():
                settings = st.session_state.get("run_settings", {})
                _, error = state.execute(
                    st.session_state["rows"],
                    st.session_state.get("run_label", "Run") + " (custom assumptions)",
                    settings={**settings, "allow_partial": True},
                )
                if error:
                    st.error(str(error))
            st.success(
                "Assumptions applied."
                + (
                    " Results updated."
                    if state.result()
                    else " Run a portfolio to see results."
                )
            )
        except ModelError as exc:
            st.error(str(exc))
    if st.session_state.get("config_overrides") and st.button(
        "Reset to the house view", icon=":material/restart_alt:"
    ):
        st.session_state.pop("config_overrides")
        if state.result():
            settings = st.session_state.get("run_settings", {})
            state.execute(
                st.session_state["rows"],
                st.session_state.get("run_label", "Run").replace(
                    " (custom assumptions)", ""
                ),
                settings=settings,
            )
        st.rerun()

# Governance -------------------------------------------------------------------------------------------------
_norm = lambda d: _json.loads(_json.dumps(d, default=list))
house_dict = _norm(base.to_dict())
with gov_tab:
    st.caption(
        "Changes to the organisation's assumptions follow maker–checker: an analyst proposes with a reason, and someone else "
        "(the head of underwriting) approves. Every proposal, decision and change of house view is in the audit log."
    )
    overrides = st.session_state.get("config_overrides") or {}
    if state.can("assumptions.propose"):
        with st.form("propose"):
            section(
                "Propose your sandbox as the new house view",
                f"{len(overrides)} change(s): {', '.join(overrides) or 'none yet — use Change assumptions first'}",
            )
            name = st.text_input("Name", value="Proposed house view")
            reason = st.text_area(
                "Why should the organisation change its assumptions?",
                placeholder="Evidence, source, expected effect…",
            )
            a, b = st.columns(2)
            propose_clicked = a.form_submit_button(
                "Submit proposal", disabled=not overrides
            )
            sandbox_clicked = b.form_submit_button(
                "Save as my sandbox only", disabled=not overrides
            )
        if (
            propose_clicked
            and state.guarded(data.propose, name, state.config().to_dict(), reason)
            is not state.FAILED
        ):
            st.success(
                "Proposal submitted. The head of underwriting has been notified."
            )
        if (
            sandbox_clicked
            and state.guarded(data.save_sandbox, name, state.config().to_dict())
            is not state.FAILED
        ):
            st.success("Saved to your sandboxes.")
    if state.can("assumptions.approve") and pending:
        section("Proposals waiting for a decision")
        for x in pending:
            with st.container(border=True):
                changes = {
                    k: v
                    for k, v in _norm(x["config"]).items()
                    if house_dict.get(k) != v
                }
                st.markdown(f"**{x['name']}** (v{x['version']}) — {x['reason']}")
                st.caption(
                    "Changes from the current house view: "
                    + (", ".join(changes) or "none")
                )
                with st.expander("Details"):
                    st.json(
                        {
                            k: {"house": house_dict.get(k), "proposed": v}
                            for k, v in changes.items()
                        }
                    )
                note = st.text_input("Decision note", key=f"note_{x['id']}")
                with st.container(horizontal=True):
                    if st.button(
                        "Approve and make house view",
                        key=f"apd_{x['id']}",
                        type="primary",
                    ):
                        if (
                            state.guarded(data.decide, x["id"], True, note, True)
                            is not state.FAILED
                        ):
                            st.rerun()
                    if st.button("Approve only", key=f"ap_{x['id']}"):
                        if (
                            state.guarded(data.decide, x["id"], True, note, False)
                            is not state.FAILED
                        ):
                            st.rerun()
                    if st.button("Reject", key=f"rj_{x['id']}"):
                        if (
                            state.guarded(data.decide, x["id"], False, note)
                            is not state.FAILED
                        ):
                            st.rerun()
    approved = [x for x in sets if x["status"] == "approved" and not x["is_default"]]
    mine = [x for x in sets if x["personal"]]
    if (state.can("assumptions.approve") and approved) or (mine and editable):
        a, b = st.columns(2, gap="large")
        if state.can("assumptions.approve") and approved:
            with a.container(border=True):
                choice = st.selectbox(
                    "Make an approved set the house view",
                    [x["id"] for x in approved],
                    format_func={
                        x["id"]: f"v{x['version']} {x['name']}" for x in approved
                    }.get,
                )
                if (
                    st.button("Use as house view")
                    and state.guarded(data.set_default, choice) is not state.FAILED
                ):
                    st.rerun()
        if mine and editable:
            with b.container(border=True):
                choice = st.selectbox(
                    "Load one of my sandboxes",
                    [x["id"] for x in mine],
                    format_func={
                        x["id"]: f"v{x['version']} {x['name']}" for x in mine
                    }.get,
                )
                if st.button("Load sandbox"):
                    cfgd = next(x for x in mine if x["id"] == choice)["config"]
                    st.session_state["config_overrides"] = {
                        k: v for k, v in _norm(cfgd).items() if house_dict.get(k) != v
                    }
                    st.rerun()
    if sets:
        section("History of assumption sets")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Version": x["version"],
                        "Name": x["name"],
                        "Status": x["status"]
                        + (" · house view" if x["is_default"] else ""),
                        "Personal": "yes" if x["personal"] else "",
                        "Reason": x["reason"] or "",
                        "Decision": x["decision_note"] or "",
                    }
                    for x in sets
                ]
            ),
            hide_index=True,
            width="stretch",
            alt="History of assumption sets",
        )
    else:
        st.caption(
            "No assumption sets yet. The house view is Xpat's documented defaults."
        )
