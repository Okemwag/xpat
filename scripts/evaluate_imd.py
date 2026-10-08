"""Evaluate the Infrastructure & Maintenance Deficit index against the 24 named hotspots, the map and chance.

Reports, in the same plain terms as the terrain proxy (AGENTS.md §3.6):
  - named-hotspot hit rate with terrain only and with the index (any tier score > 0 at the geocoded point)
  - share of the hazard-map area flagged before and after (an index that flags everything flags every hotspot)
The index is not applied to losses (the drainage model applies building density), so no portfolio figures are given.

The thresholds were fixed in configs/default.json before this script was first run; they are not tuned on its output.
Writes outputs/imd_evaluation.json and outputs/imd_evaluation.md.

Usage: uv run --extra geo python scripts/evaluate_imd.py   (after scripts/build_imd_index.py)
"""

import json
from datetime import date
from pathlib import Path
from floodcat.hazard.imd import Grid, area_comparison, hotspot_comparison
from floodcat.services.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def main():
    rt = Runtime()
    cfg = rt.config
    s = cfg.imd_index
    hot = hotspot_comparison(rt.hotspots, rt.hazard, rt.imd, s)
    array, transform, *_ , height, width = rt.hazard.grids["common"]
    area = area_comparison(array, Grid(transform.c, transform.f, transform.a, width, height), rt.imd, s)
    result = {
        "generated": date.today().isoformat(),
        "grid": dict(rt.imd.meta),
        "settings": {k: v for k, v in s.items() if k != "enabled"},
        "hotspots": hot,
        "map_area": area,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "imd_evaluation.json").write_text(json.dumps(result, indent=2, default=str) + "\n")

    n_missed = hot["hotspot_count"] - hot["flagged_terrain_only"]
    lines = [
        "# Infrastructure & Maintenance Deficit index — evaluation",
        "",
        f"Generated {result['generated']} by `scripts/evaluate_imd.py`. Inputs: `{s['grid_path']}` "
        f"({int(rt.imd.meta.get('building_count', 0)):,} OpenStreetMap buildings, {rt.imd.meta.get('extract', '?')}), "
        "the five terrain proxy maps and the 24 named hotspots. The index is an evaluation layer: it is not applied to losses.",
        "",
        "**Labels.** Index = PROXY (OSM footprints; drains and maintenance are not observed). Thresholds, weights and the "
        "score uplift = ASSUMPTION, fixed before this check was first run. Hotspot names = REAL, "
        "coordinates approximate.",
        "",
        "## Named flood areas (24)",
        "",
        f"- Terrain proxy alone flags **{hot['flagged_terrain_only']} of {hot['hotspot_count']}**.",
        f"- With the index: **{hot['flagged_with_index']} of {hot['hotspot_count']}**.",
        f"- Newly flagged: {', '.join(hot['newly_flagged']) or 'none'}.",
        f"- Still missed: {', '.join(hot['still_missed']) or 'none'}.",
        f"- Of the newly flagged, marginal (index below {hot['marginal_index']}): {', '.join(hot['marginal_new']) or 'none'}.",
        f"- Rule: {hot['rule']}.",
        "",
        "| Area | Roofed share | Buildings/ha | Index | Terrain flags it | With index |",
        "|---|---:|---:|---:|---|---|",
    ]
    for p in sorted(hot["points"], key=lambda p: -p["imd_index"]):
        lines.append(f"| {p['name']} | {p['built_fraction']:.0%} | {p['buildings_per_ha']:.0f} | {p['imd_index']:.2f} | "
                     f"{'yes' if p['terrain_flagged'] else 'no'} | {'yes' if p['flagged_with_index'] else 'no'} |")
    lines += [
        "",
        "## How much of the map it flags",
        "",
        "A hit rate means little if the whole city is flagged. Share of hazard-map cells with a score above zero (any tier):",
        "",
        f"- Terrain only: {area['share_flagged_terrain_only']:.1%}",
        f"- With the index: {area['share_flagged_with_index']:.1%} (index above zero on {area['share_index_above_zero']:.1%} of cells)",
        "",
        "## Better than chance?",
        "",
        f"Every named area is built-up (at least {area['built_up_per_ha']:g} buildings/ha in the window). Within built-up ground the index is "
        f"above zero on {area['built_up_share_index_above_zero']:.0%} of cells ({area['built_up_share_index_not_marginal']:.0%} at "
        f"{hot['marginal_index']} or more). An index switched on at random over built-up ground would therefore be expected to find about "
        f"{area['built_up_share_index_above_zero'] * n_missed:.1f} of the {n_missed} terrain misses "
        f"({area['built_up_share_index_not_marginal'] * n_missed:.1f} non-marginal); it finds {len(hot['newly_flagged'])} "
        f"({len(hot['newly_flagged']) - len(hot['marginal_new'])} non-marginal). With 12 places this is weak evidence, not proof.",
        "",
        "## Read with care",
        "",
        "- A higher hit rate is not evidence of a better model. The 24 hotspots are the only check, and 24 points cannot",
        "  separate a good index from a lucky one.",
        "- The index measures runoff pressure (roofed, crowded ground), not drainage condition. Low-density areas that flood",
        "  because drains are blocked or rivers back up will stay missed.",
        "- OpenStreetMap completeness varies: a well-mapped informal settlement reads as dense, an unmapped one as empty.",
        "  Mathare and Kiambiu are among the densest settlements in Nairobi yet read as sparse here (check mapping and the",
        "  hotspot coordinates before relying on the index there).",
        "- Roads, car parks and paved yards are not counted, so imperviousness is understated, most in commercial areas.",
        "",
        "Map data © OpenStreetMap contributors, ODbL 1.0.",
    ]
    (OUT / "imd_evaluation.md").write_text("\n".join(lines) + "\n")
    print((OUT / "imd_evaluation.md").read_text())


if __name__ == "__main__":
    main()
