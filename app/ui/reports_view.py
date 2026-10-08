"""Report downloads: PDF and Word to read and share, Excel for analysts. Built only when clicked; every download is audited."""

from datetime import datetime, timezone
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.platform import data
from . import state

FORMATS = [
    (
        "pdf",
        "PDF report",
        ":material/picture_as_pdf:",
        "To read, print or attach to a referral",
    ),
    (
        "docx",
        "Word report",
        ":material/description:",
        "To edit and add your own commentary",
    ),
    (
        "xlsx",
        "Excel workbook",
        ":material/table_view:",
        "Every table plus every property’s loss in every scenario, as numbers",
    ),
]


def _audited(fmt, analysis_id):
    state.guarded(data.record_export, analysis_id, fmt)


def report_downloads(report, key="reports"):
    """Three download buttons for the current analysis. Inputs are gathered here; the file is rendered on click (other thread)."""
    if not state.can("runs.export"):
        st.caption("Your role cannot export results.")
        return
    try:
        ylt, ranges = state.ylt(report), state.uncertainty(report)
    except ModelError:
        ylt = ranges = None
    briefing = state.current_briefing()
    names = state.people()
    with state.platform().tx() as conn:
        decisions = [
            {**d, "decided_by_name": names.get(d["decided_by"], "—")}
            for d in data.list_decisions(
                conn, state.principal(), run_id=report["analysis_id"]
            )
        ]
    inputs = dict(
        label=st.session_state.get("run_label", "Analysis"),
        organisation=state.org().get("name", ""),
        author=state.principal().display_name,
        ylt=ylt,
        ranges=ranges,
        briefing=briefing["briefing"] if briefing else None,
        decisions=decisions,
    )

    def make(kind):
        def build():
            from floodcat.reporting.document import build_document
            from floodcat.reporting.formats import render

            doc = build_document(
                report, generated_at=datetime.now(timezone.utc), **inputs
            )
            return render(doc, kind, report, ylt)[0]

        return build

    from floodcat.reporting.formats import RENDERERS

    slug = (
        "".join(c if c.isalnum() else "-" for c in inputs["label"].lower()).strip("-")[
            :40
        ]
        or "analysis"
    )
    with st.container(horizontal=True, gap="small"):
        for kind, label, icon, help_text in FORMATS:
            st.download_button(
                label,
                make(kind),
                f"xpat-{slug}.{kind}",
                RENDERERS[kind][1],
                icon=icon,
                help=help_text,
                on_click=_audited,
                args=(kind, report["analysis_id"]),
                key=f"{key}_{kind}",
            )
    included = [
        "loss curve and scenarios",
        "construction and accumulation",
        "assumptions, provenance and limitations",
    ]
    if ranges:
        included.insert(1, "damage-uncertainty ranges")
    if briefing:
        included.append("the AI briefing")
    if decisions:
        included.append(f"{len(decisions)} underwriting decision(s)")
    st.caption(
        "Includes " + ", ".join(included) + ". Downloads are recorded in the audit log."
    )
