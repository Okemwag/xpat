"""Build the Infrastructure & Maintenance Deficit (IMD) component grid from OpenStreetMap building footprints.

Reads every building outline over the hazard-map extent from a Geofabrik Kenya extract (OSM PBF; downloaded once to
runtime/osm/, gitignored, checksum verified), keeps only geometry (no tags, so no names or contact details), and writes
a 2-band GeoTIFF:

  band 1  built_fraction    footprint area / ground area within window_radius_m        (0–1)
  band 2  buildings_per_ha  building count / hectare within window_radius_m

The index itself (thresholds and weights) is applied at run time from configs/default.json, so changing those does not
need a rebuild; changing window_radius_m does. Building relations (multipolygons, well under 1% of Nairobi buildings)
are not read. Map data © OpenStreetMap contributors, ODbL 1.0.

Usage: uv run --extra osm python scripts/build_imd_index.py [--pbf PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodcat.core.config import load_config  # noqa: E402
from floodcat.hazard.imd import BANDS, Grid, footprint, neighbourhood  # noqa: E402

EXTRACT = "https://download.geofabrik.de/africa/kenya-261006.osm.pbf"


def hazard_extent():
    import rasterio

    with rasterio.open(ROOT / "data" / "nairobi_pluvial_proxy_common.tif") as ds:
        b = ds.bounds
        return b.left, b.bottom, b.right, b.top


def download(url, dest, log):
    """Fetch the extract once and check it against Geofabrik's published MD5."""
    import hashlib

    if not dest.exists():
        log(f"Downloading {url}")
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
            r.raise_for_status()
            with open(dest.with_suffix(".part"), "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        dest.with_suffix(".part").rename(dest)
    expected = httpx.get(url + ".md5", follow_redirects=True, timeout=60).text.split()[0]
    digest = hashlib.md5()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise SystemExit(f"{dest.name} does not match its published checksum; delete it and rerun")
    return dest


def read_buildings(pbf, grid, log):
    """Per-cell footprint area and building count, by centroid. Node locations are indexed on disk (low memory)."""
    import osmium

    area = np.zeros((grid.height, grid.width))
    count = np.zeros_like(area)
    south = grid.north - grid.height * grid.cell_deg
    east = grid.west + grid.width * grid.cell_deg
    stats = {"read": 0, "outside": 0, "incomplete": 0, "degenerate": 0}
    index = pbf.with_suffix(".nodes.idx")
    index.unlink(missing_ok=True)
    fp = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations(f"sparse_file_array,{index}")
        .with_filter(osmium.filter.KeyFilter("building"))
    )
    for obj in fp:
        if not obj.is_way() or obj.tags.get("building") == "no":
            continue
        try:
            ring = [(n.location.lat, n.location.lon) for n in obj.nodes]
        except osmium.InvalidLocationError:
            stats["incomplete"] += 1
            continue
        if not ring or not (south <= ring[0][0] <= grid.north and grid.west <= ring[0][1] <= east):
            stats["outside"] += 1
            continue
        fpt = footprint(ring)
        if fpt is None:
            stats["degenerate"] += 1
            continue
        rc = grid.index(*fpt[1])
        if rc:
            area[rc] += fpt[0]
            count[rc] += 1
            stats["read"] += 1
            if stats["read"] % 200_000 == 0:
                log(f"  {stats['read']:,} buildings")
    index.unlink(missing_ok=True)
    return area, count, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", type=Path, help="an OSM PBF covering Nairobi (default: download the Geofabrik Kenya extract)")
    args = ap.parse_args()
    cfg = load_config()
    settings = cfg.imd_index
    west, south, east, north = hazard_extent()
    cell = 3 / 3600  # 3 arc-seconds ≈ 93 m: nine hazard-map cells
    grid = Grid.covering(west, south, east, north, cell)
    log = lambda m: print(m, flush=True)  # noqa: E731
    if args.pbf:
        pbf, source = args.pbf, args.pbf.name
    else:
        cache = ROOT / "runtime" / "osm"
        cache.mkdir(parents=True, exist_ok=True)
        pbf, source = download(EXTRACT, cache / EXTRACT.rsplit("/", 1)[1], log), EXTRACT
    log(f"Reading buildings from {pbf.name}")
    area, count, stats = read_buildings(pbf, grid, log)
    comp = neighbourhood(area, count, grid, settings["window_radius_m"])
    out = ROOT / settings["grid_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    import rasterio

    tags = {
        "title": "Infrastructure & Maintenance Deficit index components (Nairobi)",
        "source": "OpenStreetMap building footprints; © OpenStreetMap contributors, ODbL 1.0",
        "extract": source,
        "building_count": str(int(count.sum())),
        "skipped_ways": json.dumps({k: v for k, v in stats.items() if k != "read"}),
        "window_radius_m": str(settings["window_radius_m"]),
        "cell_deg": repr(cell),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": "PROXY",
        "script": "scripts/build_imd_index.py",
    }
    with rasterio.open(out, "w", driver="GTiff", height=grid.height, width=grid.width, count=len(BANDS),
                       dtype="float32", crs="EPSG:4326", transform=grid.transform(), compress="deflate",
                       predictor=3) as ds:
        for i, b in enumerate(BANDS, 1):
            ds.write(comp[b].astype("float32"), i)
            ds.set_band_description(i, b)
        ds.update_tags(**tags)
    (out.with_suffix(".json")).write_text(json.dumps(tags, indent=2) + "\n")
    log(f"Wrote {out.relative_to(ROOT)}: {int(count.sum()):,} buildings, grid {grid.width}×{grid.height}")


if __name__ == "__main__":
    main()
