"""Flood reports → local embeddings → drainage-deficit factor per place → evidence for review (evidence page tab)."""

import hashlib
import streamlit as st
from floodcat.ai import drainage
from floodcat.ai.reports import from_upload, ingest, reliefweb_available, reliefweb_search
from floodcat.core.errors import ModelError
from floodcat.platform import data
from . import state
from .charts import hbars, place_factor_map
from .components import explain, kpis, section


def _mode_status(mode, allowed):
    """(usable, reason) for one processing mode on this server, for this organisation and user."""
    from floodcat.ai.llm import configured

    if mode not in allowed:
        return False, "turned off by your organisation"
    if mode == "local":
        try:
            import fastembed  # noqa: F401
        except ImportError:
            return False, "local embeddings are not installed on this server"
        return True, ""
    if not configured(mode):
        return False, "not configured on this server"
    if not state.ai_enabled("evidence"):
        return False, "AI is off for your organisation or role"
    return True, ""


def _process(reports, mode, independent, settings):
    rt = state.runtime()
    llm = rt.llm(mode) if mode != "local" else None
    gazetteer = rt.gazetteer(with_ai_fallback=False) if mode != "local" else None
    added, skipped, failed = 0, [], []
    bar = st.progress(0.0, "Reading reports…")
    for i, r in enumerate(reports, 1):
        bar.progress(i / len(reports), f"{i}/{len(reports)} · {r['title'][:60]}")
        if mode != "local" and not state.ai_quota():
            break
        try:
            doc = ingest(r, rt.embedder, rt.scorer(settings), rt.places, settings, mode, llm, gazetteer)
            doc["independent"] = independent
            with state.platform().tx() as conn:
                data.add_report(conn, state.principal(), doc, request=state.request_info())
            added += 1
        except ModelError as exc:
            (skipped if exc.code == "duplicate_report" else failed).append(f"{r['title'][:60]}: {exc}")
    bar.empty()
    if added:
        st.success(f"{added} report(s) added.", icon=":material/check:")
    if skipped:
        st.info(f"{len(skipped)} already in the library (same text).")
    for f in failed:
        st.warning(f)


def flood_reports_tab(store):
    rt = state.runtime()
    cfg = state.config()
    settings = cfg.drainage_reports
    allowed = state.org().get("settings", {}).get("report_modes", list(drainage.MODES))
    try:
        rt.places
    except ModelError as exc:
        st.warning(f"{exc}. Reports cannot be matched to places until it is built.", icon=":material/map:")
        return

    # Mode ----------------------------------------------------------------------------------------------------
    status = {m: _mode_status(m, allowed) for m in drainage.MODES}
    usable_modes = [m for m in drainage.MODES if status[m][0]]
    left, right = st.columns([3, 2], gap="large", vertical_alignment="bottom")
    with left:
        mode = st.segmented_control(
            "How to read the reports",
            drainage.MODES,
            default=usable_modes[0] if usable_modes else None,
            format_func=lambda m: {"local": "Local only", "ollama": "Local + Ollama", "gemini": "Local + Gemini"}[m],
            key="report_mode",
        )
    with right:
        st.caption(" · ".join(f"**{m}**: {'ready' if ok else why}" for m, (ok, why) in status.items()))
    if mode and not status[mode][0]:
        st.warning(f"{drainage.MODE_LABELS[mode]} is unavailable: {status[mode][1]}.")
        mode = None
    st.caption({
        "local": "Embeddings and place matching run on this server; no text generation, nothing leaves the server. Fastest.",
        "ollama": "Embeddings pick the drainage passages; a local Llama model names place and cause in those passages only.",
        "gemini": "Embeddings pick the drainage passages; only those passages (contact details removed) go to Google Gemini.",
        None: "No mode is available.",
    }[mode])
    consent = True
    if mode == "gemini":
        consent = st.checkbox("I agree to send the selected drainage passages (contact details removed) to Google Gemini.")

    # Add reports -----------------------------------------------------------------------------------------------
    can_add = state.can("evidence.add") and mode is not None and consent and not state.read_only()
    up, rw = st.columns(2, gap="large")
    with up.container(border=True, height="stretch"):
        section("Upload reports", "PDF, Word, text, or a CSV of articles with a text column")
        files = st.file_uploader("Reports", type=["pdf", "docx", "txt", "md", "csv"], accept_multiple_files=True,
                                 label_visibility="collapsed", key="report_files")
        independent = st.checkbox("These sources are independent of the county's flood-area list", value=True, key="rep_ind",
                                  help="Untick for material that copies the government hotspot list; it is then excluded from the hit-rate check.")
        if st.button("Process uploads", type="primary", icon=":material/upload:", disabled=not (can_add and files)):
            reports = []
            for f in files:
                raw = f.getvalue()
                if not state.screen_upload(raw, hashlib.sha256(raw).hexdigest()):
                    continue
                try:
                    reports += from_upload(raw, f.name)
                except ModelError as exc:
                    st.warning(f"{f.name}: {exc}")
            if reports:
                _process(reports, mode, independent, settings)
    with rw.container(border=True, height="stretch"):
        section("Search ReliefWeb", "Public humanitarian reports on Kenya")
        if not reliefweb_available():
            st.caption("Not configured: set RELIEFWEB_APPNAME (a free app name from apidoc.reliefweb.int).")
        query = st.text_input("Search terms", "Nairobi flood drainage", key="rw_q")
        a, b, c = st.columns(3)
        d_from = a.date_input("From", value=None, key="rw_from")
        d_to = b.date_input("To", value=None, key="rw_to")
        limit = c.number_input("Reports", 1, 200, 20, key="rw_n")
        if st.button("Fetch and process", icon=":material/travel_explore:", disabled=not (can_add and reliefweb_available())):
            try:
                with st.spinner("Searching ReliefWeb…"):
                    found = reliefweb_search(query, d_from and d_from.isoformat(), d_to and d_to.isoformat(), int(limit))
                if not found:
                    st.info("No reports matched.")
                else:
                    _process(found, mode, True, settings)
            except ModelError as exc:
                st.error(str(exc))

    # Results ---------------------------------------------------------------------------------------------------
    with state.platform().tx() as conn:
        docs = data.list_reports(conn, state.principal())
    if not docs:
        st.info("No reports yet. Upload some or search ReliefWeb.")
        return
    places = drainage.place_factors(docs, settings)
    existing = {e.evidence_id: e for e in store.list_evidence()}
    min_conf = cfg.evidence_min_confidence
    kpis([
        ("Reports", len(docs), f"{sum(d['source_kind'] == 'reliefweb' for d in docs)} from ReliefWeb"),
        ("Passages", sum(d["chunk_count"] for d in docs), "Embedded locally"),
        ("Drainage passages", sum(d["drainage_chunks"] for d in docs), "Similar to drainage failure, not river overflow"),
        ("Places with a factor", len(places), f"{sum(p['factor'] >= min_conf for p in places)} at {min_conf:.0%} or more"),
    ])

    section("Drainage-deficit factor by place", "Combines independent reports; each report counts once")
    mleft, mright = st.columns([3, 2], gap="large")
    with mleft.container(border=True, height="stretch"):
        st.pydeck_chart(place_factor_map(places), height=380, alt="Places with a drainage-deficit factor from flood reports")
        explain(
            "Places named in drainage passages of the reports. Larger, darker circles = higher factor.",
            "The factor rises as more independent reports describe drainage failure there: one strong report ≈ 0.5–1, "
            "each further report closes part of the gap to 1. It is not a probability or a depth.",
            ["AI", "REAL"],
            source="flood reports · local embeddings · OpenStreetMap place names ·",
        )
    with mright.container(border=True, height="stretch"):
        rows = [{"Place": p["place"], "Factor": p["factor"], "Reports": p["report_count"], "_label": f"{p['factor']:.2f}"}
                for p in places[:15]]
        chart = hbars(rows, "Place", "Factor", "Drainage-deficit factor (0–1)", text="_label")
        if chart:
            st.altair_chart(chart, width="stretch")
        st.caption(f"Evidence changes hazard only from {min_conf:.0%} and only after a reviewer approves it.")

    for p in places[:25]:
        ev = drainage.to_evidence(p)
        sent = existing.get(ev.evidence_id)
        with st.container(border=True):
            top = st.container(horizontal=True, vertical_alignment="center")
            top.markdown(f"**{p['place']}** · factor **{p['factor']:.2f}** · {p['report_count']} report(s)"
                         + ("" if p["all_independent"] else " · includes non-independent sources"))
            if sent:
                top.badge("approved" if sent.approved else "awaiting review", color="green" if sent.approved else "orange")
            elif top.button("Send to review", key=f"send_{ev.evidence_id}", icon=":material/rate_review:",
                            disabled=not state.can("evidence.add")):
                try:
                    store.add_evidence(ev)
                    st.rerun()
                except ModelError:
                    pass
            best = p["reports"][0]
            st.markdown(f"> {best['quote'][:600]}{'…' if len(best['quote']) > 600 else ''}")
            st.caption(" · ".join(f"{r['title'][:70]} ({r['strength']:.2f}, {r['method']})" for r in p["reports"][:4]))

    # Semantic search -------------------------------------------------------------------------------------------
    section("Search the reports", "Meaning, not keywords: “water ponding because culverts are blocked” finds paraphrases")
    q = st.text_input("Search", placeholder="e.g. sewers backing up into homes", label_visibility="collapsed", key="rep_search")
    if q.strip():
        import numpy as np

        with state.platform().tx() as conn:
            chunks = data.report_chunks_for(conn, state.principal())
        titles = {d["id"]: d["title"] for d in docs}
        if chunks:
            sims = np.stack([c["vector"] for c in chunks]) @ rt.embedder.embed_queries([q])[0]
            for i in np.argsort(-sims)[:8]:
                c = chunks[i]
                with st.container(border=True):
                    st.markdown(f"**{sims[i]:.2f}** similarity · {titles.get(c['document_id'], '')[:80]}"
                                + (f" · drainage {c['strength']:.2f}" if c["strength"] > 0 else ""))
                    st.write(c["text"][:700])

    # Library ---------------------------------------------------------------------------------------------------
    with st.expander(f"Report library ({len(docs)})", icon=":material/library_books:"):
        for d in docs:
            row = st.container(horizontal=True, vertical_alignment="center")
            row.markdown(f"**{d['title'][:90]}** · {d['published'] or 'no date'} · {d['chunk_count']} passages, "
                         f"{d['drainage_chunks']} drainage · {len(d['assessments'])} place(s) · {d['mode']}"
                         + (f" ({d['model']})" if d.get("model") else ""))
            if mode and row.button("Re-assess", key=f"re_{d['id']}", help=f"Name places again using {drainage.MODE_LABELS[mode]}",
                                   disabled=not can_add):
                _reassess(d, mode, settings)
            if row.button("Delete", key=f"rdel_{d['id']}", icon=":material/delete:"):
                if state.guarded(data.delete_report, d["id"]) is not state.FAILED:
                    st.rerun()


def _reassess(doc, mode, settings):
    rt = state.runtime()
    with state.platform().tx() as conn:
        chunks = data.report_chunks_for(conn, state.principal(), doc["id"])
    try:
        if mode == "local":
            assessments, model = drainage.assess_local(chunks, rt.places, settings["place_lookback_chunks"]), None
        else:
            if not state.ai_quota():
                return
            assessments, model = drainage.assess_llm(chunks, doc["title"], rt.llm(mode), rt.places, settings,
                                                     rt.gazetteer(with_ai_fallback=False))
    except ModelError as exc:
        st.error(str(exc))
        return
    if state.guarded(data.update_report_assessments, doc["id"], assessments, mode, model) is not state.FAILED:
        st.rerun()
