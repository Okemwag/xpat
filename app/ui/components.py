import streamlit as st
from streamlit.errors import StreamlitAPIException
from floodcat.core.constants import TIERS
from floodcat.exposure.validation import summarise_issues
from . import state

LABELS = {
    "REAL": ("green", "Observed, published or real client data"),
    "PROXY": ("orange", "Derived from real inputs, not a measurement"),
    "SYNTHETIC": ("violet", "Generated or test data — not real properties"),
    "ASSUMPTION": ("gray", "A modelling choice we made and state openly"),
    "AI": ("blue", "Produced or changed by the AI stage, with evidence"),
}


def badges(*labels):
    cols = st.container(horizontal=True, gap="small")
    for label in labels:
        color, help_text = LABELS[label]
        with cols:
            st.badge(label, color=color, help=help_text)


def page_header(title, subtitle=None, labels=()):
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if labels:
        badges(*labels)


def require_result():
    """Stop the page with a helpful prompt if no portfolio has been run yet."""
    report = state.result()
    if report is None:
        with st.container(border=True):
            st.subheader("No portfolio loaded yet")
            if state.can("runs.create"):
                st.write(
                    "Upload a schedule or a broker document, describe buildings in plain English, or start from the 600-property sample portfolio."
                )
                if st.button("Go to Portfolio", type="primary"):
                    st.switch_page("views/portfolio.py")
            elif state.can("runs.read"):
                st.write("Open an analysis your colleagues have shared with you.")
                if st.button("Go to Reports & history", type="primary"):
                    st.switch_page("views/history.py")
            else:
                st.write(
                    "Your role administers the organisation; it does not run or read analyses. Use the Administration pages."
                )
        st.stop()
    return report


def run_banner(report):
    cfg = state.config()
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        st.markdown(
            f"**{st.session_state.get('run_label', 'Current run')}** · {report['modelled_count']} properties modelled · "
            f"{state.kes(report['modelled_tiv_kes'])} insured · max depth {cfg.max_depth_m:g} m"
        )
        for label in report.get("exposure_origin", {}).get("labels", ["SYNTHETIC"]):
            st.badge(f"{label.lower()} data", color=LABELS[label][0])
        if report["partial"]:
            st.badge(
                f"{len(report['excluded_from_hazard']) + report['rejected_count']} excluded",
                color="orange",
            )
        if report["ai_contribution"]["enabled"]:
            st.badge(
                "AI evidence applied", color="blue", icon=":material/auto_awesome:"
            )
        if st.session_state.get("config_overrides"):
            st.badge("custom assumptions", color="gray")


def headline_tiles(report, run="baseline"):
    cfg = state.config()
    curve = {p["return_period_years"]: p for p in report["runs"][run]["ep_curve"]}
    rps = sorted(curve)
    hundred = 100.0 if 100.0 in curve else rps[len(rps) // 2]
    rarest = rps[-1]
    cols = st.columns(4)
    cols[0].metric(
        "Total insured value",
        state.kes(report["modelled_tiv_kes"]),
        border=True,
        help="Sum of insured values of the properties that could be modelled. SYNTHETIC.",
    )
    cols[1].metric(
        f"{state.rp_label(hundred)} loss",
        state.kes(curve[hundred]["loss_kes"]),
        border=True,
        help=f"A loss at least this large has an assumed {1 / hundred:.1%} chance in any year. "
        f"{state.pct(curve[hundred]['loss_pct_of_tiv'])} of insured value.",
    )
    cols[2].metric(
        f"{state.rp_label(rarest)} loss",
        state.kes(curve[rarest]["loss_kes"]),
        border=True,
        help=f"Assumed {1 / rarest:.1%} chance in any year. {state.pct(curve[rarest]['loss_pct_of_tiv'])} of insured value.",
    )
    cols[3].metric(
        "Average annual loss",
        state.kes(report["runs"][run]["aal"]["aal_kes"]),
        border=True,
        help="Long-run yearly average implied by the curve. Assumes no loss below a "
        f"{state.rp_label(cfg.aal_zero_loss_return_period)} event and the rarest loss held beyond it.",
    )
    st.caption(
        f"{state.rp_label(hundred)}: {state.pct(curve[hundred]['loss_pct_of_tiv'])} of value · "
        f"{state.rp_label(rarest)}: {state.pct(curve[rarest]['loss_pct_of_tiv'])} of value · "
        "Return periods are ASSUMPTIONS mapped to the five hazard tiers; losses are gross (no policy terms)."
    )


def issues_panel(issues, expanded=False):
    groups = summarise_issues(issues)
    if not groups:
        st.success("Every record passed validation.", icon=":material/check_circle:")
        return
    errors = sum(g["count"] for g in groups if g["severity"] == "error")
    warnings = sum(g["count"] for g in groups if g["severity"] == "warning")
    if errors:
        st.error(
            f"{errors} record(s) cannot be modelled as they are.",
            icon=":material/error:",
        )
    if warnings:
        st.warning(
            f"{warnings} warning(s) — the records are modelled, but check these.",
            icon=":material/warning:",
        )
    for g in groups:
        icon = ":material/error:" if g["severity"] == "error" else ":material/warning:"
        with st.expander(
            f"{g['code'].replace('_', ' ')} — {g['count']} record(s)",
            icon=icon,
            expanded=expanded and g["severity"] == "error",
        ):
            st.write(g["example"])
            ids = ", ".join(i for i in g["loc_ids"] if i)
            if ids:
                st.caption(
                    f"Examples: {ids}"
                    + (" …" if g["count"] > len(g["loc_ids"]) else "")
                )


def tier_selector(key, default_rp=100.0, label="Return period"):
    cfg = state.config()
    options = [cfg.return_periods[t] for t in TIERS]
    default = default_rp if default_rp in options else options[-1]
    chosen = st.segmented_control(
        label, options, default=default, format_func=state.rp_label, key=key
    )
    chosen = chosen or default
    return state.tier_for_rp(cfg, chosen), chosen


STAGES = [
    (
        "Hazard",
        "views/map.py",
        ":material/water:",
        "Flood-severity score at each property",
    ),
    (
        "Vulnerability",
        "views/assumptions.py",
        ":material/home:",
        "Score → depth → damage ratio by construction",
    ),
    (
        "Exposure",
        "views/portfolio.py",
        ":material/apartment:",
        "Properties, construction and insured value",
    ),
    (
        "Financial engine",
        "views/property.py",
        ":material/calculate:",
        "Damage × value per property, summed per event",
    ),
    (
        "Loss curve",
        "views/results.py",
        ":material/show_chart:",
        "10,000 simulated years → loss vs rarity",
    ),
]


def pipeline_strip(active=None):
    """The model chain as a clickable strip. `active` is the stage name of the current page."""
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for i, (name, page, icon, help_text) in enumerate(STAGES):
            label = f"**{name}**" if name == active else name
            try:
                st.page_link(page, label=label, icon=icon, help=help_text)
            except StreamlitAPIException:  # page not registered (e.g. a page rendered on its own): show the stage as text
                st.markdown(f"{icon} {label}", help=help_text)
            if i < len(STAGES) - 1:
                st.markdown("→")


def explain(what, how, labels, source=None):
    """Provenance badges plus a collapsed "How to read" (what it shows / how to read it / where it comes from)."""
    row = st.container(horizontal=True, gap="small", vertical_alignment="center")
    for label in labels:
        color, help_text = LABELS[label]
        row.badge(label, color=color, help=help_text)
    with row.popover("How to read", icon=":material/info:", type="tertiary"):
        st.markdown(f"**What it shows** — {what}")
        st.markdown(f"**How to read it** — {how}")
        if source:
            st.markdown(f"**Where it comes from** — {source}")


def kpis(items, columns=None):
    """A row of headline numbers: items are (label, value) or (label, value, help) or (label, value, help, delta)."""
    items = [i for i in items if i]
    cols = st.columns(columns or len(items))
    for col, item in zip(cols, items):
        label, value, *rest = item
        col.metric(
            label,
            value,
            delta=rest[1] if len(rest) > 1 else None,
            help=rest[0] if rest else None,
            border=True,
            delta_color="off" if len(rest) > 1 else "normal",
        )


def section(title, caption=None):
    st.markdown(f"#### {title}")
    if caption:
        st.caption(caption)


def link(label, url, primary=True, icon=""):
    """A button-styled link that opens in the same tab (for the auth pages)."""
    import html

    style = (
        "background:#2a78d6;color:#fff;border:1px solid #2a78d6"
        if primary
        else "color:#2a78d6;border:1px solid #2a78d6;background:transparent"
    )
    st.markdown(
        f'<a href="{html.escape(url, quote=True)}" target="_self" style="display:inline-block;padding:.5rem 1rem;border-radius:.5rem;'
        f'text-decoration:none;font-weight:600;{style}">{html.escape(icon + " " if icon else "")}{html.escape(label)}</a>',
        unsafe_allow_html=True,
    )


def when(rows, fmt="%d %b %Y %H:%M"):
    """Format a datetime (or ISO string) for tables."""
    from datetime import datetime

    if rows is None:
        return "—"
    if isinstance(rows, str):
        try:
            rows = datetime.fromisoformat(rows)
        except ValueError:
            return rows
    return rows.strftime(fmt)
