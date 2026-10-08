"""Hazard checks: the drainage-aware hazard (AI enhancement 1) and the satellite flood check (AI enhancement 3)."""

import hashlib
import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.hazard.drainage import FEATURES, hit_rate
from ui import state
from ui.components import badges, explain, kpis, page_header, pipeline_strip, section

page_header(
    "Hazard checks",
    "The baseline map finds 12 of 24 named flood areas: it cannot see drains. Add a drainage model, and test any map "
    "against water seen by satellite radar after a real flood.",
)
pipeline_strip("Hazard")
rt = state.runtime()
cfg = state.config()
FEATURE_TEXT = {
    "low_terrain": "Low ground near rivers (the baseline score)",
    "built_density": "Dense buildings — sealed ground, fast runoff",
    "drain_gap": "Far from any mapped drain or ditch",
    "culvert_proximity": "Close to a culvert, where debris blocks flow",
}
drain_tab, sat_tab = st.tabs(
    [
        ":material/water_drop: Drainage model",
        ":material/satellite_alt: Satellite flood check",
    ]
)


def adjustment(evidence):
    """Fitted once per evidence set, config and satellite points (fitting is deterministic)."""
    extra = tuple(st.session_state.get("sat_positives", ()))
    key = (
        tuple(
            sorted(
                e.evidence_id + str(e.approved) + str(e.independent_of_hotspot_list)
                for e in evidence
            )
        ),
        cfg.fingerprint,
        hash(extra),
    )
    held = st.session_state.get("drainage_fit")
    if held and held[0] == key:
        return held[1]
    adj = rt.drainage_adjustment(evidence, cfg, extra)
    st.session_state["drainage_fit"] = (key, adj)
    return adj


with drain_tab:
    badges("PROXY", "AI", "ASSUMPTION")
    with st.expander("How the drainage model works", icon=":material/help:"):
        st.markdown(f"""
For every point it measures four things from OpenStreetMap and the baseline map, each scaled 0–1: {", ".join(f"**{FEATURE_TEXT[f].lower()}**" for f in FEATURES)}.
A logistic formula turns them into a drainage-failure probability. Where it exceeds **{cfg.drainage_model["probability_threshold"]:.0%}**, hazard is raised with
the same formula as reviewed evidence, by up to **{cfg.drainage_model["weight"]:.0%}** of the remaining headroom (more for rarer tiers).

- **Prior weights** (ASSUMPTION, `configs/default.json`) are used until there are at least {cfg.drainage_model["min_training_positives"]} approved,
  independent flood reports to learn from.
- **Learned weights** (AI) come from those reports against {cfg.drainage_model["background_points"]} random background points (seed {cfg.drainage_model["seed"]}).
  The 24 named hotspots are **never** used to learn — they are the test.
- The probability is a severity uplift, not a depth and not a measured chance of flooding. OSM maps drains unevenly, so in informal areas a
  “drain gap” can mean nobody mapped the drain.
""")
    if not state.drainage_ready():
        st.info(
            "The OpenStreetMap drainage layers are not built on this server yet. An administrator runs "
            "`uv run python scripts/build_drainage_layers.py` (about 10 minutes, needs internet) and restarts the app.",
            icon=":material/build:",
        )
    else:
        evidence = state.org_evidence()
        try:
            adj = adjustment(evidence)
            check = hit_rate(rt.hotspots, rt.hazard, adj)
        except ModelError as exc:
            st.error(str(exc), icon=":material/error:")
            st.stop()
        summary = adj.summary()
        kpis(
            [
                (
                    "Weights",
                    "Learned from evidence"
                    if summary["mode"] == "fitted"
                    else "Prior (assumed)",
                    summary["training"].get("reason"),
                ),
                (
                    "Named hotspots flagged",
                    f"{check['after_flagged']} of {check['hotspot_count']}",
                    "With the drainage model",
                    f"{check['after_flagged'] - check['before_flagged']:+d} vs the map alone ({check['before_flagged']})",
                ),
                (
                    "Mapped drains",
                    f"{summary['layers']['drain_segments']:,} segments",
                    f"{summary['layers']['culverts']:,} culverts",
                ),
                (
                    "Buildings",
                    f"{summary['layers']['buildings']:,}",
                    f"OSM, fetched {summary['layers_fetched'] or '—'}",
                ),
            ]
        )
        left, right = st.columns([2, 3], gap="large")
        with left.container(border=True, height="stretch"):
            section(
                "What raises the probability",
                "Weight per feature; positive = more likely to flood",
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Feature": FEATURE_TEXT[f],
                            "Weight": round(summary["weights"][f], 2),
                        }
                        for f in FEATURES
                    ]
                    + [
                        {
                            "Feature": "Intercept (baseline level)",
                            "Weight": round(summary["intercept"], 2),
                        }
                    ]
                ),
                hide_index=True,
                width="stretch",
                alt="Drainage model weights",
            )
            if summary["mode"] == "fitted":
                t = summary["training"]
                st.caption(
                    f"Learned from {t['positives']} flood points and {t['background']} background points. Average probability: "
                    f"{t['mean_p_positive']:.0%} at flood points vs {t['mean_p_background']:.0%} at background points (training data, not a test)."
                )
            explain(
                "The weights that turn the four features into a drainage-failure probability.",
                "A bigger positive weight means that feature pushes the probability up more. Prior weights are our assumption; learned weights come from reviewed evidence.",
                ["AI" if summary["mode"] == "fitted" else "ASSUMPTION", "PROXY"],
                source="OpenStreetMap (ODbL) · baseline proxy rasters · approved evidence",
            )
        with right.container(border=True, height="stretch"):
            section(
                "Named-hotspot check",
                "Same 24 places and the same rule (score above zero) as the baseline check",
            )
            table = pd.DataFrame(
                [
                    {
                        "Hotspot": p["name"],
                        "Before (common tier)": p["before_common"],
                        "After (common tier)": p["after_common"],
                        "Flagged after": "✓" if p["after_flagged"] else "✗",
                        "Newly flagged": "★"
                        if p["name"] in check["newly_flagged"]
                        else "",
                    }
                    for p in check["points"]
                ]
            )
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                height=320,
                alt="Hotspot scores before and after the drainage model",
                column_config={
                    "Before (common tier)": st.column_config.ProgressColumn(
                        format="%.3f", min_value=0, max_value=1
                    ),
                    "After (common tier)": st.column_config.ProgressColumn(
                        format="%.3f", min_value=0, max_value=1
                    ),
                },
            )
            for caveat in check["caveats"]:
                st.caption(f"• {caveat}")
        report = state.result()
        if report is not None and state.can("runs.create"):
            label = st.session_state.get("run_label", "Run").replace(
                " + drainage model", ""
            )
            if st.button(
                "Re-run the current portfolio with the drainage model",
                type="primary",
                icon=":material/water_drop:",
            ):
                settings = {
                    **st.session_state.get("run_settings", {}),
                    "drainage": True,
                    "drainage_evidence": evidence,
                    "drainage_extra_positives": tuple(
                        st.session_state.get("sat_positives", ())
                    ),
                }
                _, error = state.execute(
                    st.session_state["rows"],
                    label + " + drainage model",
                    settings=settings,
                )
                if error:
                    st.error(str(error))
                else:
                    st.switch_page("views/overview.py")

with sat_tab:
    badges("REAL", "PROXY")
    st.write(
        "Upload a flood map made from Sentinel-1 radar with the UN-SPIDER method (`scripts/gee_sentinel1_flood.js` exports one for "
        "the March–May 2024 rains). The check samples flooded and dry pixels and asks how often the hazard map flags each."
    )
    st.caption(
        "Radar under-detects water among buildings, so street flooding in dense areas is often missing; read results mainly along the "
        "Nairobi, Ngong and Mathare river corridors. Change detection is not AI: this is the independent test for the AI adjustments."
    )
    file = st.file_uploader(
        "Flood-extent GeoTIFF (1 = flooded, 0 = dry)",
        type=["tif", "tiff"],
        key="sat_upload",
    )
    if file is not None:
        data = file.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        if state.screen_upload(data, digest):
            from floodcat.hazard.satellite import FloodExtent, compare, training_points

            try:
                extent = FloodExtent.read(data)
                base = compare(extent, rt.hazard, cfg, rt.hotspots)
                drained = None
                if state.drainage_ready():
                    from floodcat.hazard.drainage import DrainedHazard

                    drained = compare(
                        extent,
                        DrainedHazard(
                            rt.hazard, rt.drainage_adjustment(state.org_evidence(), cfg)
                        ),
                        cfg,
                    )
            except ModelError as exc:
                st.error(str(exc), icon=":material/error:")
                st.stop()
            kpis(
                [
                    (
                        "Flooded pixels the map flags",
                        f"{base['hit_rate_any_pct']:.0f}%",
                        f"{base['flooded_points']} sampled flooded pixels, any tier",
                        f"{drained['hit_rate_any_pct'] - base['hit_rate_any_pct']:+.0f} pts with drainage model"
                        if drained
                        else None,
                    ),
                    (
                        "Dry pixels the map flags",
                        f"{base['dry_flag_rate_any_pct']:.0f}%",
                        f"{base['dry_points']} sampled dry pixels — lower is better",
                        f"{drained['dry_flag_rate_any_pct'] - base['dry_flag_rate_any_pct']:+.0f} pts with drainage model"
                        if drained
                        else None,
                    ),
                    (
                        "Named hotspots with water nearby",
                        f"{sum(1 for h in base['hotspots_with_observed_water'] if h['flooded_nearby'])} of {len(rt.hotspots)}",
                        "Flooded pixel within about 100 m of the centre",
                    ),
                ]
            )
            rows = [
                {
                    "Tier": f"{t} ({state.rp_label(cfg.return_periods[t])})",
                    "Flooded pixels flagged (%)": base["hit_rate_pct"][t],
                    "Dry pixels flagged (%)": base["dry_flag_rate_pct"][t],
                    **(
                        {
                            "Flooded flagged, drainage model (%)": drained[
                                "hit_rate_pct"
                            ][t]
                        }
                        if drained
                        else {}
                    ),
                }
                for t in TIERS
            ]
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                alt="Satellite check by tier",
            )
            explain(
                "How often each tier flags pixels the radar saw flooded, against pixels it saw dry.",
                "A useful map flags flooded pixels far more often than dry ones. Neither number is an accuracy; one flood is one sample of weather.",
                ["REAL", "PROXY"],
                source="Sentinel-1 (Copernicus) via the UN-SPIDER method · baseline proxy rasters",
            )
            for caveat in base["caveats"]:
                st.caption(f"• {caveat}")
            if drained:
                st.caption(
                    "• The drainage-model column uses a model fitted without these satellite pixels, so the check is not circular."
                )
            if st.checkbox(
                "Also use flooded pixels to teach the drainage model",
                key="sat_teach",
                help="Adds sampled flooded pixels as training points (positives). They are independent of the hotspot list.",
            ):
                st.session_state["sat_positives"] = training_points(extent, cfg, 100)
            else:
                st.session_state.pop("sat_positives", None)
