from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.ai.evidence import usable
from ui import state
from ui.charts import portfolio_map
from ui.charts import hbars
from ui.components import (
    explain,
    kpis,
    page_header,
    pipeline_strip,
    require_result,
    run_banner,
    section,
    tier_selector,
)

page_header("Accumulation map")
pipeline_strip("Hazard")
report = require_result()
run_banner(report)
cfg = state.config()
c1, c2 = st.columns([2, 1])
with c1:
    tier, rp = tier_selector("map_tier")
with c2:
    runs = ["baseline"] + (["enhanced"] if "enhanced" in report["runs"] else [])
    run = (
        st.radio(
            "Model",
            runs,
            horizontal=True,
            format_func={"baseline": "Baseline", "enhanced": "With AI evidence"}.get,
        )
        if len(runs) > 1
        else "baseline"
    )

color_by = (
    st.segmented_control(
        "Colour properties by",
        ["score", "loss"],
        default="score",
        format_func={"score": "Hazard score", "loss": "Loss"}.get,
    )
    or "score"
)
from html import (
    escape as _h,
)  # tooltips are rendered as HTML: escape every uploaded value

rows = report["runs"][run]["property_losses"][tier]
points = [
    {
        "lat": r["lat"],
        "lon": r["lon"],
        "loss": float(r["loss_kes"]),
        "tiv": float(r["tiv_kes"]),
        "score": r["hazard_score"],
        "tooltip": f"<b>{_h(r['loc_id'])}</b> · {state.class_label(r['housing_class'])}<br/>"
        f"Insured value {state.kes(r['tiv_kes'])}<br/>"
        + (
            f"Terrain score {r['terrain_score']:.3f} + infrastructure index {r['imd_index']:.2f}<br/>"
            if "imd_index" in r
            else ""
        )
        + f"Hazard score {r['hazard_score']:.3f} ({tier}, {state.rp_label(rp)}) → depth {r['assumed_depth_m']:.2f} m<br/>"
        f"Damage ratio {r['damage_ratio']:.1%}<br/>"
        + (
            f"Flood-exposed share of value {r['exposed_fraction']:.0%} (storeys)<br/>"
            if r.get("exposed_fraction", 1) < 1
            else ""
        )
        + f"<b>Loss = {state.kes(r['tiv_kes'])} × {r['damage_ratio']:.1%}"
        + (
            f" × {r['exposed_fraction']:.0%}"
            if r.get("exposed_fraction", 1) < 1
            else ""
        )
        + f" = {state.kes(r['loss_kes'])}</b>"
        + (
            f"<br/>Nearest hotspot: {_h(r['nearest_hotspot'])} ({r['hotspot_distance_m'] / 1000:.1f} km)"
            if r.get("nearest_hotspot")
            else ""
        ),
    }
    for r in rows
]
from floodcat.platform.data import list_evidence

with state.platform().tx() as _c:
    _ev = [e for e, _ in list_evidence(_c, state.principal().org_id)]
evidence = usable(_ev, cfg) if run == "enhanced" else ()
st.pydeck_chart(
    portfolio_map(points, state.runtime().hotspots, evidence, color_by=color_by),
    height=540,
)
explain(
    f"All {len(points)} properties. Dot size = insured value; colour = {'hazard score (0–1)' if color_by == 'score' else 'loss'} at {state.rp_label(rp)} "
    "(light = none, dark blue = highest). Orange rings: the 24 government-named flood hotspots"
    + (
        "; purple circles: approved AI drainage evidence and its reach."
        if evidence
        else "."
    ),
    "Hover a property to trace its loss: class → insured value → hazard score → depth → damage ratio → loss. Big dark dots close "
    "together are concentrations a single flood could hit at once. Grey dots are not flagged by the proxy — not proof they cannot flood.",
    list(
        dict.fromkeys([*state.exposure_labels(report), "PROXY", "REAL", "ASSUMPTION"])
    ),
    source=f"{state.exposure_words(report)} · proxy hazard map · named hotspots (approximate) ·",
)

b = report["runs"][run]["breakdowns"][tier]
total_tiv = sum(Decimal(r["tiv_kes"]) for r in rows) or Decimal(1)
flagged_tiv = sum(Decimal(r["tiv_kes"]) for r in rows if r["hazard_score"] > 0)
named = [a for a in b.get("hotspot_area", []) if not a["id"].startswith("no named")]
kpis(
    [
        ("Properties", len(rows)),
        ("Insured value", state.kes(total_tiv)),
        ("Value in flagged locations", f"{flagged_tiv / total_tiv:.0%}"),
        (
            "Top named area",
            named[0]["id"] if named else "—",
            f"{named[0]['loss_share_pct']:.0f}% of loss" if named else None,
        ),
    ]
)
left, right = st.columns(2, gap="large")
with left.container(border=True):
    section(
        "Loss by named flood area",
        f"Within {cfg.hotspot_tag_radius_m / 1000:g} km of a named area",
    )
    chart = hbars(
        [
            {
                "Area": a["id"]
                if not a["id"].startswith("no named")
                else "Away from named areas",
                "Share (%)": round(a["loss_share_pct"], 1),
                "Loss": state.kes(a["loss_kes"]),
                "Properties": a["property_count"],
                "_label": f"{a['loss_share_pct']:.0f}%",
            }
            for a in b.get("hotspot_area", [])[:10]
        ],
        "Area",
        "Share (%)",
        "Share of loss (%)",
        text="_label",
    )
    if chart:
        st.altair_chart(chart, width="stretch")
with right.container(border=True):
    section(f"Value by {cfg.grid_size_m / 1000:g} km cell", "Top cells by loss")
    chart = hbars(
        [
            {
                "Cell": g["id"],
                "Value (%)": round(float(Decimal(g["tiv_kes"]) / total_tiv * 100), 1),
                "Loss": state.kes(g["loss_kes"]),
                "Properties": g["property_count"],
                "_label": state.kes(g["loss_kes"]),
            }
            for g in b["geographic_grid"][:10]
        ],
        "Cell",
        "Value (%)",
        "Share of portfolio value (%)",
        text="_label",
        color="#eb6834",
    )
    if chart:
        st.altair_chart(chart, width="stretch")
