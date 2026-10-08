"""What a submission document says: the five capabilities of ai/document_analysis.py, one tab each."""

import pandas as pd
import streamlit as st
from . import state
from .components import badges


def document_analysis_panel(analysis, report=None, key="doc"):
    if not analysis:
        return
    from floodcat.ai.document_analysis import implied_metrics

    points, rel, hist = analysis["data_points"], analysis["relevance"], analysis["flood_history"]
    implied = implied_metrics(points, report) if report else analysis["implied"]
    with st.container(border=True):
        st.markdown("**What the document says**")
        badges("AI", "REAL")
        cols = st.columns(4)
        cols[0].metric("Data points found", points["count"], help="Each kept only with a quote found word-for-word in the document")
        cols[1].metric("Flood-relevant sections", f"{len(rel['relevant'])} of {len(rel['relevant']) + len(rel['irrelevant'])}")
        cols[2].metric("Flood events reported", len(hist["events"]))
        cols[3].metric("Arithmetic checks", f"{sum(c['ok'] for c in implied['checks'])} of {len(implied['checks'])} agree")
        t1, t2, t3, t4, t5 = st.tabs([
            "Data points across the text", "Relevant vs irrelevant", "Building vs risk indicators",
            "Flood history", "Implied risk metrics",
        ])
        with t1:
            st.dataframe(pd.DataFrame([{"Term": t["label"], "Value": (f"{t['value_number']:,.2f}".rstrip("0").rstrip(".")
                                        if t["value_number"] is not None else t["value_text"]), "Quote": t["quote"]}
                                       for t in points["terms"]]), hide_index=True, width="stretch")
            if points["missing"]:
                st.warning("Not stated in the document: " + ", ".join(points["missing"]) +
                           ". The model uses the house default for anything missing; ask the broker.", icon=":material/help:")
            if points["unverified"]:
                st.caption(f"{len(points['unverified'])} value(s) dropped: their quote was not found in the document.")
        with t2:
            a, b = st.columns(2, gap="large")
            with a:
                st.markdown(f"**Relevant to a flood loss ({len(rel['relevant'])})**")
                for x in rel["relevant"]:
                    st.markdown(f"- **{x['heading'][:70]}** · {x['topic']} — {x['reason']}")
            with b:
                st.markdown(f"**Set aside ({len(rel['irrelevant'])})**")
                for x in rel["irrelevant"]:
                    st.markdown(f"- {x['heading'][:70]} · {x['topic']} — {x['reason']}")
        with t3:
            for c in analysis["cross_reference"]:
                st.markdown(f"**{c['property']}**")
                st.dataframe(pd.DataFrame([{"Indicator": r["indicator"], "Document says": r["document"], "Model": r["model"],
                                            "Flag": r["flag"] or "—"} for r in c["rows"]]), hide_index=True, width="stretch")
        with t4:
            st.write(hist["summary"])
            if hist["events"]:
                st.dataframe(pd.DataFrame([{"When": e["date_text"] or e["year"], "Where": e["place"], "What": e["description"],
                                            "Cause": e["cause"], "Depth (m)": e["depth_m"],
                                            "Loss": state.kes(e["loss_kes"]) if e["loss_kes"] else "—"} for e in hist["events"]]),
                             hide_index=True, width="stretch")
            for q in hist.get("ask_for") or []:
                st.markdown(f"- Ask for: {q}")
        with t5:
            st.dataframe(pd.DataFrame([{"Metric": m["metric"], "Value": m["value"], "How": m["how"]} for m in implied["metrics"]]),
                         hide_index=True, width="stretch")
            for c in implied["checks"]:
                (st.success if c["ok"] else st.error)(
                    f"{c['check']}: expected {c['expected']}, document says {c['stated']}",
                    icon=":material/check:" if c["ok"] else ":material/error:")
            if not report:
                st.caption("Modelled loss against premium and sum insured appears here and on Overview once the model has run.")
