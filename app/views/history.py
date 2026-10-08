from collections import Counter
import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.platform import data
from floodcat.reporting.export import json_report, property_csv
from floodcat.reporting.summary import markdown_summary
from ui import state
from ui.charts import timeline
from ui.components import kpis, page_header, run_banner, section, when
from ui.reports_view import report_downloads

p = state.principal()
page_header(
    "Reports & history",
    "Download the current results as PDF, Word or Excel, or reopen an analysis you or your colleagues have shared.",
)


def audited(fmt):
    report = state.result()
    if report:
        state.guarded(data.record_export, report["analysis_id"], fmt)


report = state.result()
if report:
    with st.container(border=True):
        section("Current analysis")
        run_banner(report)
        report_downloads(report, key="history_reports")
        if p.can("runs.export"):
            with st.expander(
                "Other formats: summary, raw JSON, property CSVs",
                icon=":material/folder_zip:",
            ):
                cfg = state.config()
                try:
                    ranges, ylt = state.uncertainty(report), state.ylt(report)
                except ModelError:
                    ranges = ylt = None
                summary = markdown_summary(report, ranges, ylt)
                if state.current_briefing():
                    from floodcat.ai.briefing import to_markdown

                    summary += "\n---\n\n" + to_markdown(
                        state.current_briefing()["briefing"]
                    )
                tier = st.selectbox(
                    "Property losses for",
                    TIERS,
                    index=len(TIERS) - 1,
                    format_func=lambda t: (
                        f"{state.rp_label(cfg.return_periods[t])} ({t})"
                    ),
                )
                with st.container(horizontal=True):
                    st.download_button(
                        "Summary (Markdown)",
                        summary,
                        "xpat_summary.md",
                        "text/markdown",
                        icon=":material/description:",
                        on_click=audited,
                        args=("markdown",),
                    )
                    st.download_button(
                        "Full report (JSON)",
                        json_report(report),
                        "xpat_report.json",
                        "application/json",
                        icon=":material/data_object:",
                        on_click=audited,
                        args=("json",),
                    )
                    for run in report["runs"]:
                        st.download_button(
                            f"Property losses CSV ({'AI' if run == 'enhanced' else 'baseline'})",
                            property_csv(report, run, tier),
                            f"xpat_property_losses_{run}_{tier}.csv",
                            "text/csv",
                            icon=":material/table:",
                            key=f"csv_{run}",
                            on_click=audited,
                            args=("csv",),
                        )

with state.platform().tx() as conn:
    runs = data.list_runs(conn, p)
    from floodcat.platform.orgs import list_teams

    teams = {t["id"]: t["name"] for t in list_teams(conn, p.org_id)}
names = state.people()
section("Analyses you can see")
if not runs:
    st.info(
        "No analyses yet. Every analysis you run is saved here automatically.",
        icon=":material/history:",
    )
    st.stop()
mine_count = sum(r["owner_id"] == p.user_id for r in runs)
kpis(
    [
        ("Analyses", len(runs)),
        ("Yours", mine_count),
        ("Shared with you", len(runs) - mine_count),
        ("With AI evidence", sum(bool(r["summary"].get("ai_enabled")) for r in runs)),
        ("On real data", sum("REAL" in r["summary"].get("origin", []) for r in runs)),
    ]
)
per_day = Counter(when(r["created_at"], "%Y-%m-%d") for r in runs)
chart = timeline(
    [{"Day": d, "Analyses": n} for d, n in sorted(per_day.items())],
    "Day",
    "Analyses",
    "Analyses",
    height=150,
)
if chart and len(per_day) > 1:
    st.altair_chart(chart, width="stretch", alt="Analyses run per day")

with st.container(horizontal=True, vertical_alignment="bottom"):
    who = (
        st.segmented_control(
            "Show",
            ["all", "mine", "shared"],
            default="all",
            format_func={"all": "All", "mine": "Mine", "shared": "Shared with me"}.get,
        )
        or "all"
    )
    query = st.text_input(
        "Search by name", placeholder="e.g. Landmark", label_visibility="collapsed"
    )
shown = [
    r
    for r in runs
    if (who == "all" or (who == "mine") == (r["owner_id"] == p.user_id))
    and query.lower() in r["label"].lower()
]
VIS = {"private": "only me", "team": "my team", "org": "whole organisation"}
for r in shown:
    s = r["summary"]
    with st.container(border=True):
        top = st.container(horizontal=True, vertical_alignment="center")
        top.markdown(
            f"**{r['label']}**  \n{when(r['created_at'])} · by {names.get(r['owner_id'], 'a former member')} · {s['modelled_count']} properties · "
            f"{state.kes(s['modelled_tiv_kes'])} insured · AAL {state.kes(s['aal_kes'])}"
            + f" · visible to {VIS[r['visibility']]}"
            + (
                f" ({teams.get(r['team_id'], 'team')})"
                if r["visibility"] == "team"
                else ""
            )
        )
        for label in s.get("origin", []):
            top.badge(label.lower(), color="green" if label == "REAL" else "violet")
        if s.get("ai_enabled"):
            top.badge("AI evidence", color="blue", icon=":material/auto_awesome:")
        if report and report["analysis_id"] == r["id"]:
            top.badge("open now", color="gray")
        if top.button("Open", key=f"open_{r['id']}", icon=":material/open_in_new:"):
            try:
                with state.platform().tx() as conn:
                    run = data.get_run(
                        conn,
                        p,
                        r["id"],
                        with_inputs=p.can("runs.create"),
                        request=state.request_info(),
                    )
                state.set_result(
                    run["payload"], run.get("inputs", []), r["label"], run["settings"]
                )
                st.session_state["config_overrides"] = {}
                st.switch_page("views/overview.py")
            except ModelError as exc:
                st.error(str(exc))
        if r["owner_id"] == p.user_id:
            vis = top.selectbox(
                "Share with",
                list(VIS),
                index=list(VIS).index(r["visibility"]),
                format_func=VIS.get,
                key=f"vis_{r['id']}",
                label_visibility="collapsed",
                width=200,
            )
            if (
                vis != r["visibility"]
                and state.guarded(
                    data.set_visibility,
                    r["id"],
                    vis,
                    p.team_ids[0] if vis == "team" and p.team_ids else None,
                )
                is not state.FAILED
            ):
                st.rerun()
        if (r["owner_id"] == p.user_id or p.can("runs.delete_any")) and top.button(
            "Delete", key=f"del_{r['id']}", icon=":material/delete:"
        ):
            if state.guarded(data.delete_run, r["id"]) is not state.FAILED:
                st.rerun()
if not shown:
    st.caption("No analyses match.")
