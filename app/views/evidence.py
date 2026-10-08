import hashlib
from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.ai.evaluation import hotspot_comparison
from floodcat.ai.evidence import Evidence, usable
from floodcat.core.constants import MECHANISMS, TIERS
from floodcat.core.errors import ModelError
from floodcat.platform import data
from ui import state
from ui.charts import ylt_chart
from ui.components import badges, explain, kpis, page_header, section

page_header(
    "AI flood evidence",
    "The baseline map cannot see drainage failures. Turn flood reports into reviewed evidence and measure what it changes.",
)
rt = state.runtime()
cfg = state.config()


class OrgEvidence:
    """The organisation's evidence library (tenant-scoped, maker-checker, audited)."""

    def add_evidence(self, item):
        if state.guarded(data.add_evidence, item) is state.FAILED:
            raise ModelError("failed", "Not added")

    def list_evidence(self):
        with state.platform().tx() as conn:
            return [e for e, _ in data.list_evidence(conn, state.principal().org_id)]

    def creators(self):
        with state.platform().tx() as conn:
            return {
                e.evidence_id: meta["created_by"]
                for e, meta in data.list_evidence(conn, state.principal().org_id)
            }

    def approve_evidence(self, evidence_id, _reviewer=None):
        return state.guarded(data.approve_evidence, evidence_id)

    def update_evidence(self, evidence_id, **_):
        return state.guarded(data.withdraw_evidence, evidence_id)

    def delete_evidence(self, evidence_id):
        return state.guarded(data.delete_evidence, evidence_id)


store = OrgEvidence()
MECH_LABEL = {
    "drainage": "Drainage failure",
    "surface_runoff": "Surface runoff / ponding",
    "river_overflow": "River overflow",
    "other": "Other",
    "unknown": "Unknown",
}

with st.expander(
    "How this works and what it can and cannot prove", icon=":material/help:"
):
    st.markdown(f"""
0. **Flood reports** — upload many reports or fetch them from ReliefWeb. They are split into passages and embedded on this
   server; passages that read like drainage failure (not river overflow) name places from an OpenStreetMap list, or a chosen
   language model names them. Each place gets a **drainage-deficit factor** that grows with the number of independent reports.
   "Send to review" turns a place into an evidence item (confidence = factor), which then follows steps 2–4.
1. **Extract** — paste a flood report. The AI model proposes places, dates, mechanism and a verbatim quote. Quotes not found in the
   report are dropped; places are located with OpenStreetMap (an AI estimate is used only as a flagged fallback).
2. **Review** — a reviewer checks each item, fixes the location if needed, and states whether the source is **independent of the
   county's hotspot list**. Nothing affects the model until a named reviewer approves it.
3. **Apply** — approved *{" / ".join(MECH_LABEL[m].lower() for m in cfg.evidence_mechanisms)}* evidence with confidence ≥ {cfg.evidence_min_confidence:.0%}
   raises hazard within {cfg.evidence_radius_m:g} m, fading with distance, by up to {cfg.uplift_weight:.0%} of the remaining headroom (more for rarer tiers).
   River overflow is excluded: the proxy already models rivers.
4. **Measure** — the loss curve before and after, the properties that changed, and how many of the 24 named hotspots are flagged
   before and after — counting **only independent evidence**, because evidence taken from the hotspot list itself would make the check circular.
""")

_all = store.list_evidence()
_applied = usable(_all, cfg)
_check = hotspot_comparison(rt.hotspots, rt.hazard, _all, cfg)
kpis(
    [
        ("Evidence items", len(_all), "Extracted or added by hand"),
        ("Approved", sum(e.approved for e in _all), "By a named reviewer"),
        (
            "Awaiting review",
            sum(not e.approved for e in _all),
            "No effect until approved",
        ),
        (
            "Changing the hazard",
            len(_applied),
            "Approved drainage / runoff, confident enough",
        ),
        (
            "Named hotspots flagged",
            f"{_check['after_flagged']} of {_check['hotspot_count']}",
            "Independent evidence only",
            f"{_check['after_flagged'] - _check['before_flagged']:+d} vs the map alone ({_check['before_flagged']})",
        ),
    ]
)
badges("AI", "REAL", "ASSUMPTION")

reports_tab, extract_tab, library_tab, impact_tab, manual_tab = st.tabs(
    [
        ":material/article: Flood reports",
        ":material/auto_awesome: Extract from one report",
        ":material/library_books: Evidence library",
        ":material/compare_arrows: Impact on losses",
        ":material/edit_location: Add manually",
    ]
)


def add_candidates(candidates, independent):
    added = 0
    for c in candidates:
        if c["lat"] is None:
            continue
        try:
            store.add_evidence(
                Evidence(
                    **{
                        k: c[k]
                        for k in (
                            "evidence_id",
                            "source",
                            "quote",
                            "event_date",
                            "location_name",
                            "lat",
                            "lon",
                            "location_method",
                            "mechanism",
                            "confidence",
                        )
                    },
                    independent_of_hotspot_list=independent,
                )
            )
            added += 1
        except ModelError as exc:
            st.warning(f"{c['location_name']}: {exc}")
    return added


with reports_tab:
    from ui.flood_reports_view import flood_reports_tab

    flood_reports_tab(store)

with extract_tab:
    if not state.ai_enabled("evidence"):
        st.warning(
            "AI evidence extraction is unavailable here — not configured on this server, or turned off by your organisation. You can still add evidence manually.",
            icon=":material/key_off:",
        )
    source = st.text_input(
        "Source (URL or publication and date)",
        max_chars=500,
        placeholder="https://… or “Daily Nation, 25 April 2024”",
    )
    text = st.text_area(
        "Report text",
        height=200,
        max_chars=30000,
        placeholder="Paste the article or report passage here.",
    )
    independent = st.checkbox(
        "This source is independent of the county's list of 37 flood-prone areas",
        value=True,
        help="Untick for articles that reproduce the government hotspot list. They can still change losses but are excluded from the hit-rate check.",
    )
    if st.button(
        "Extract evidence",
        type="primary",
        icon=":material/auto_awesome:",
        disabled=not state.ai_enabled("evidence")
        or not text.strip()
        or not source.strip(),
    ):
        from floodcat.ai.extraction import extract

        if not state.ai_quota():
            st.stop()
        try:
            with st.spinner(
                f"{state.ai_name()} is reading the report; locating places…"
            ):
                st.session_state["extraction"] = extract(
                    text, source, rt.llm(), rt.gazetteer()
                ) | {"independent": independent}
        except ModelError as exc:
            st.error(str(exc), icon=":material/error:")
    ex = st.session_state.get("extraction")
    if ex:
        st.caption(
            f"Model {ex['model']} · prompt {ex['prompt_version']} · {len(ex['candidates'])} candidate(s), {len(ex['dropped'])} dropped"
        )
        if ex["dropped"]:
            with st.expander("Dropped by the quote check"):
                for d in ex["dropped"]:
                    st.write(f"- {d['location_name'] or '?'}: {d['reason']}")
        if ex["candidates"]:
            frame = pd.DataFrame(ex["candidates"])
            edited = st.data_editor(
                frame,
                hide_index=True,
                width="stretch",
                key="cand_editor",
                column_config={
                    "evidence_id": None,
                    "source": None,
                    "status": None,
                    "quote": st.column_config.TextColumn(
                        "quote", disabled=True, width="large"
                    ),
                    "mechanism": st.column_config.SelectboxColumn(
                        "mechanism", options=list(MECHANISMS)
                    ),
                    "confidence": st.column_config.NumberColumn(
                        "confidence", min_value=0.0, max_value=1.0, step=0.05
                    ),
                    "lat": st.column_config.NumberColumn("lat", format="%.5f"),
                    "lon": st.column_config.NumberColumn("lon", format="%.5f"),
                    "location_method": st.column_config.TextColumn(
                        "located by", disabled=True
                    ),
                },
            )
            st.caption(
                "Fix any location (lat/lon) or mechanism before adding. Rows without coordinates are skipped. "
                "“ai_estimate” locations are guesses — check them on a map."
            )
            if st.button(
                "Add to the evidence library (unapproved)",
                icon=":material/library_add:",
            ):
                records = edited.to_dict("records")
                for r in records:
                    if pd.isna(r["lat"]) or pd.isna(r["lon"]):
                        r["lat"] = r["lon"] = None
                    elif r["location_method"] == "ai_estimate" and (
                        r["lat"],
                        r["lon"],
                    ) != next(
                        (
                            (c["lat"], c["lon"])
                            for c in ex["candidates"]
                            if c["evidence_id"] == r["evidence_id"]
                        ),
                        None,
                    ):
                        r["location_method"] = "manual"
                n = add_candidates(records, ex["independent"])
                st.success(
                    f"{n} item(s) added. A reviewer must approve them in the Evidence library."
                )
                st.session_state.pop("extraction")

with manual_tab:
    st.write("Record a flood observation from a source you have read yourself.")
    with st.form("manual"):
        a, b = st.columns(2)
        name = a.text_input("Place name")
        source_m = b.text_input("Source (URL or reference)")
        quote = st.text_area("Supporting quote (verbatim)", max_chars=2000)
        c, d, e = st.columns(3)
        lat = c.number_input("Latitude", -1.45, -1.10, -1.29, 0.0001, format="%.5f")
        lon = d.number_input("Longitude", 36.60, 37.00, 36.82, 0.0001, format="%.5f")
        event_date = e.date_input("Event date", value=None)
        f, g = st.columns(2)
        mechanism = f.selectbox("Mechanism", MECHANISMS, format_func=MECH_LABEL.get)
        confidence = g.slider(
            "How clearly does the source say it flooded?", 0.0, 1.0, 0.8, 0.05
        )
        independent_m = st.checkbox(
            "Independent of the county hotspot list", value=True
        )
        submitted = st.form_submit_button("Add evidence (unapproved)", type="primary")
    if submitted:
        try:
            digest = hashlib.sha256(f"{source_m}|{name}|{quote}".encode()).hexdigest()[
                :12
            ]
            store.add_evidence(
                Evidence(
                    f"ev-{digest}",
                    source_m,
                    quote,
                    event_date.isoformat() if event_date else "",
                    name,
                    lat,
                    lon,
                    "manual",
                    mechanism,
                    confidence,
                    independent_m,
                )
            )
            st.success("Added. A reviewer must approve it.")
        except ModelError as exc:
            st.error(str(exc))

with library_tab:
    items = store.list_evidence()
    if not items:
        st.info("No evidence yet. Extract it from a report or add it manually.")
    applied_ids = {e.evidence_id for e in usable(items, cfg)}
    for e in items:
        with st.container(border=True):
            top = st.container(horizontal=True, vertical_alignment="center")
            top.markdown(
                f"**{e.location_name}** · {MECH_LABEL[e.mechanism]} · confidence {e.confidence:.0%}"
                + (f" · {e.event_date}" if e.event_date else "")
            )
            if e.approved:
                top.badge(
                    f"approved by {e.reviewer}", color="green", icon=":material/check:"
                )
            else:
                top.badge("awaiting review", color="orange")
            if e.evidence_id in applied_ids:
                top.badge("changes hazard", color="blue")
            elif e.approved:
                top.badge("not applied (mechanism or confidence)", color="gray")
            if not e.independent_of_hotspot_list:
                top.badge(
                    "from hotspot list — excluded from hit-rate check", color="gray"
                )
            st.markdown(f"> {e.quote}")
            st.caption(
                f"Source: {e.source} · located by {e.location_method} at {e.lat:.4f}, {e.lon:.4f}"
            )
            actions = st.container(horizontal=True)
            if state.can_review():
                if not e.approved and actions.button(
                    "Approve", key=f"ap_{e.evidence_id}", icon=":material/check:"
                ):
                    if store.approve_evidence(e.evidence_id) is not state.FAILED:
                        st.rerun()
                if e.approved and actions.button(
                    "Withdraw approval", key=f"wd_{e.evidence_id}"
                ):
                    if store.update_evidence(e.evidence_id) is not state.FAILED:
                        st.rerun()
                if actions.button(
                    "Delete", key=f"del_{e.evidence_id}", icon=":material/delete:"
                ):
                    if store.delete_evidence(e.evidence_id) is not state.FAILED:
                        st.rerun()
            else:
                actions.caption("Only reviewers can approve evidence.")

with impact_tab:
    applied = _applied
    report = state.result()
    if not applied:
        st.info(
            "Approve at least one drainage or surface-runoff item to see its effect."
        )
    elif report is None:
        st.info("Run a portfolio first (Portfolio page).")
    elif st.button(
        "Re-run the current portfolio with AI evidence",
        type="primary",
        icon=":material/auto_awesome:",
    ):
        settings = st.session_state.get("run_settings", {})
        _, error = state.execute(
            st.session_state["rows"],
            st.session_state.get("run_label", "Run").replace(" + AI evidence", "")
            + " + AI evidence",
            settings={**settings, "ai_adjustment": True, "evidence": applied},
        )
        if error:
            st.error(str(error))
        else:
            st.rerun()
    report = state.result()
    if report and report["ai_contribution"]["enabled"]:
        ai = report["ai_contribution"]
        section("What the AI evidence changed")
        rarest = TIERS[-1]
        kpis(
            [
                ("Properties with raised hazard", ai["changed_properties"]),
                (
                    f"Change in {state.rp_label(cfg.return_periods[rarest])} loss",
                    state.kes(ai["loss_delta_kes"][rarest]),
                ),
                ("Change in average annual loss", state.kes(ai["aal_delta_kes"])),
            ]
        )
        if ai.get("spread"):
            st.caption(
                f"{ai['spread']['changed_near_hotspot']} changed properties are within {cfg.hotspot_tag_radius_m / 1000:g} km of a named hotspot; "
                f"{ai['spread']['changed_away_from_hotspots']} are further away."
            )
        st.altair_chart(
            ylt_chart(state.ylt(report), report, compare_ai=True),
            width="stretch",
            alt="Loss curve before and after AI drainage evidence",
        )
        explain(
            "The loss curve before (blue) and after (orange) applying approved drainage evidence, each from 10,000 simulated years.",
            "Where the orange curve sits above the blue, the evidence raised losses. A higher loss is not proof of a better model — the "
            "named-hotspot check below is the evidence.",
            ["AI", "ASSUMPTION"],
        )

    section(
        "Named-hotspot check",
        "Does approved, independent evidence help the map find the 24 places the county says flood?",
    )
    comparison = _check
    kpis(
        [
            (
                "Flagged before (baseline map)",
                f"{comparison['before_flagged']} of {comparison['hotspot_count']}",
            ),
            (
                "Flagged after (independent evidence only)",
                f"{comparison['after_flagged']} of {comparison['hotspot_count']}",
                None,
                f"{comparison['after_flagged'] - comparison['before_flagged']:+d} hotspots",
            ),
        ]
    )
    st.caption(
        f"{comparison['evaluated_evidence_count']} independent item(s) evaluated; {comparison['excluded_non_independent']} excluded as non-independent."
        + (
            f" Newly flagged: {', '.join(comparison['newly_flagged'])}."
            if comparison["newly_flagged"]
            else ""
        )
    )
    table = pd.DataFrame(
        [
            {
                "Hotspot": p["name"],
                "Before (common tier)": p["before_common"],
                "After (common tier)": p["after_common"],
                "Flagged before": p["before_flagged"],
                "Flagged after": p["after_flagged"],
            }
            for p in comparison["points"]
        ]
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        alt="Hazard score at each named hotspot before and after evidence",
        column_config={
            "Before (common tier)": st.column_config.ProgressColumn(
                format="%.3f", min_value=0, max_value=1
            ),
            "After (common tier)": st.column_config.ProgressColumn(
                format="%.3f", min_value=0, max_value=1
            ),
        },
    )
    for caveat in comparison["caveats"]:
        st.caption(f"• {caveat}")
