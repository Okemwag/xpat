"""Build the offline Nairobi place-name gazetteer used to find places in flood reports (no LLM, no network at run time).

Reads named `place=*` nodes and closed ways over the hazard-map extent from the Geofabrik Kenya extract that
scripts/build_imd_index.py downloads (runtime/osm/). Ways use the mean of their nodes. The county hotspot list is NOT an
input, so places found in reports are independent of it. Writes outputs/nairobi_places.json.
Map data © OpenStreetMap contributors, ODbL 1.0.

Usage: uv run --extra osm --extra geo python scripts/build_places.py [--pbf PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodcat.ai.places import RANK  # noqa: E402

DEFAULT_PBF = ROOT / "runtime" / "osm" / "kenya-261006.osm.pbf"


def hazard_extent():
    import rasterio

    with rasterio.open(ROOT / "data" / "nairobi_pluvial_proxy_common.tif") as ds:
        b = ds.bounds
        return b.left, b.bottom, b.right, b.top


def read_places(pbf, extent):
    import osmium

    west, south, east, north = extent
    out = []
    index = pbf.with_suffix(".places.idx")
    index.unlink(missing_ok=True)
    fp = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations(f"sparse_file_array,{index}")
        .with_filter(osmium.filter.KeyFilter("place"))
    )
    for obj in fp:
        kind, name = obj.tags.get("place"), obj.tags.get("name")
        if kind not in RANK or not name:
            continue
        if obj.is_node():
            lat, lon = obj.location.lat, obj.location.lon
        elif obj.is_way():
            try:
                pts = [(n.location.lat, n.location.lon) for n in obj.nodes]
            except osmium.InvalidLocationError:
                continue
            lat, lon = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        else:
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        alt = [a.strip() for key in ("alt_name", "old_name", "short_name") for a in obj.tags.get(key, "").split(";") if a.strip()]
        out.append({"name": name.strip(), "alt_names": alt, "place": kind, "lat": round(lat, 6), "lon": round(lon, 6),
                    "osm": f"{'node' if obj.is_node() else 'way'}/{obj.id}"})
    index.unlink(missing_ok=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", type=Path, default=DEFAULT_PBF)
    args = ap.parse_args()
    if not args.pbf.exists():
        raise SystemExit(f"{args.pbf} not found: run `make imd-index` first (it downloads the extract)")
    places = read_places(args.pbf, hazard_extent())
    doc = {
        "source": "OpenStreetMap place=* nodes and ways; © OpenStreetMap contributors, ODbL 1.0",
        "extract": args.pbf.name,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/build_places.py",
        "provenance": "REAL (names) · approximate centres",
        "places": sorted(places, key=lambda p: (RANK[p["place"]], p["name"])),
    }
    out = ROOT / "outputs" / "nairobi_places.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {out.relative_to(ROOT)}: {len(places)} places")


if __name__ == "__main__":
    main()
