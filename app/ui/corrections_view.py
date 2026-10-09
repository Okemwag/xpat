"""Switches for the two corrections to places the terrain map misses: the drainage model and approved flood evidence.

Either one raises hazard scores before vulnerability, so the change flows through damage, property losses, the loss
curve, policy terms and reinsurance (services/analysis.py). The baseline run is always kept beside the corrected one.
"""

import streamlit as st
from floodcat.ai.evidence import usable
from ui import state

SUFFIXES = {"drainage": " + drainage model", "evidence": " + AI evidence"}
CORRECTION_KEYS = ("drainage", "drainage_evidence", "drainage_extra_positives", "ai_adjustment", "evidence")


def active(settings):
    """Which corrections a run's settings switch on."""
    settings = settings or {}
    return {"drainage": bool(settings.get("drainage")), "evidence": bool(settings.get("ai_adjustment"))}


def with_corrections(settings, label, drainage, evidence, org_evidence=(), applied=(), extra_positives=()):
    """The run settings and label with exactly the chosen corrections; every other setting is kept."""
    out = {k: v for k, v in (settings or {}).items() if k not in CORRECTION_KEYS}
    if drainage:
        out.update(drainage=True, drainage_evidence=tuple(org_evidence), drainage_extra_positives=tuple(extra_positives))
    if evidence:
        out.update(ai_adjustment=True, evidence=list(applied))
    base = label or "Run"
    for suffix in SUFFIXES.values():
        base = base.replace(suffix, "")
    chosen = {"drainage": drainage, "evidence": evidence}
    return out, base + "".join(s for k, s in SUFFIXES.items() if chosen[k])


def _inputs():
    org_evidence = state.org_evidence()
    return state.drainage_ready(), org_evidence, usable(org_evidence, state.config())


def _toggles(current, key, drainage_ok, applied, disabled=False):
    st.markdown("**Correct for places the terrain map misses**")
    st.caption(
        "The terrain map finds 12 of the 24 named flood areas; the rest flood because drains fail. Each switch raises hazard "
        "near drainage problems, and the higher scores carry through damage, loss, the loss curve, policy terms and "
        "reinsurance. The uncorrected run is kept beside it for comparison."
    )
    left, right = st.columns(2)
    drainage = left.toggle(
        "Drainage model (OpenStreetMap)",
        value=current["drainage"] and drainage_ok,
        key=f"{key}_drainage",
        disabled=disabled or not drainage_ok,
        help="Drains, culverts and building density → chance of drainage failure; hazard is raised where it exceeds the "
        "threshold in the assumptions. Flags 21 of 24 named areas (12 without), not validated: building density does most of the work."
        if drainage_ok
        else "The drainage layers are not built on this server. An administrator runs scripts/build_drainage_layers.py.",
    )
    evidence = right.toggle(
        f"Approved flood evidence ({len(applied)} item{'s' if len(applied) != 1 else ''})",
        value=current["evidence"] and bool(applied),
        key=f"{key}_evidence",
        disabled=disabled or not applied,
        help="Drainage and runoff reports approved by a named reviewer raise hazard near each reported place (AI flood evidence page)."
        if applied
        else "No approved drainage or runoff evidence yet. Add and approve it on the AI flood evidence page.",
    )
    return {"drainage": drainage, "evidence": evidence}


def chosen_settings(settings, label, choice):
    """Settings and label for a new run with the choice made on the Portfolio page."""
    drainage_ok, org_evidence, applied = _inputs()
    return with_corrections(
        settings,
        label,
        choice["drainage"] and drainage_ok,
        choice["evidence"] and bool(applied),
        org_evidence,
        applied,
        st.session_state.get("sat_positives", ()),
    )


def portfolio_panel():
    """Before a run: remember the choice for the next run. Returns {"drainage": bool, "evidence": bool}."""
    drainage_ok, _, applied = _inputs()
    remembered = st.session_state.setdefault("corrections", {"drainage": False, "evidence": False})
    with st.container(border=True):
        choice = _toggles(remembered, "pf_corr", drainage_ok, applied)
    st.session_state["corrections"] = choice
    return choice


def results_panel(report):
    """After a run: switching re-runs the current portfolio with the chosen corrections, saved as a new run."""
    drainage_ok, org_evidence, applied = _inputs()
    settings = st.session_state.get("run_settings", {})
    current = active(settings)
    with st.container(border=True):
        choice = _toggles(current, f"res_corr_{report['analysis_id']}", drainage_ok, applied, disabled=not state.can("runs.create"))
    if choice == current or not st.session_state.get("rows"):
        return
    new_settings, label = with_corrections(
        settings,
        st.session_state.get("run_label", "Run"),
        choice["drainage"],
        choice["evidence"],
        org_evidence,
        applied,
        st.session_state.get("sat_positives", ()),
    )
    with st.spinner("Re-running hazard → vulnerability → loss…"):
        _, error = state.execute(st.session_state["rows"], label, settings=new_settings)
    if error:
        st.error(str(error), icon=":material/error:")
        return
    st.session_state["corrections"] = choice
    st.rerun()
