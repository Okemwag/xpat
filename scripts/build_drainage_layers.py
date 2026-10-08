"""Build the OSM drainage layers used by the drainage-aware hazard (hazard/drainage.py).

Usage:
    uv run python scripts/build_drainage_layers.py                       # query the Overpass API (network; resumable)
    uv run python scripts/build_drainage_layers.py --from-dir saved/     # convert saved Overpass JSON files (offline)
    uv run --with osmium python scripts/build_drainage_layers.py --geofabrik   # faster: one Kenya extract from Geofabrik, cut locally

Writes runtime/drainage/osm_layers.json (gitignored; regenerate on each server). Contents:
  drains    — ways tagged waterway=drain or waterway=ditch, as [lon, lat] lines
  culverts  — midpoints of ways tagged tunnel=culvert
  buildings — centroids of ways tagged building=*
Data © OpenStreetMap contributors, ODbL. OSM drain mapping is uneven across Nairobi; see docs/AI_ENHANCEMENTS.md.
"""

import argparse
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runtime" / "drainage" / "osm_layers.json"
OVERPASS = "https://overpass-api.de/api/interpreter"
MIRRORS = (
    OVERPASS,
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
BBOX = "-1.45,36.60,-1.10,37.00"  # south, west, north, east (configs: NAIROBI_BOUNDS)
TILES = 4  # buildings are fetched in TILES × TILES boxes so no single request is too large for the public server
QUERIES = {
    "drains": f'[out:json][timeout:300];way["waterway"~"^(drain|ditch)$"]({BBOX});out geom;',
    "culverts": f'[out:json][timeout:300];way["tunnel"="culvert"]({BBOX});out geom;',
    "buildings": '[out:json][timeout:600];way["building"]({box});out center qt;',
}
RAW = ROOT / "runtime" / "drainage" / "raw"


def tiles():
    south, west, north, east = (float(x) for x in BBOX.split(","))
    dy, dx = (north - south) / TILES, (east - west) / TILES
    return [
        f"{south + i * dy:.4f},{west + j * dx:.4f},{south + (i + 1) * dy:.4f},{west + (j + 1) * dx:.4f}"
        for i in range(TILES)
        for j in range(TILES)
    ]


def overpass(query, attempts=6):
    for attempt in range(attempts):
        server = MIRRORS[
            attempt % len(MIRRORS)
        ]  # public Overpass servers drop large replies; rotate between them
        request = urllib.request.Request(
            server,
            data=urllib.parse.urlencode({"data": query}).encode(),
            headers={"User-Agent": "xpat-nairobi-flood-hackathon/0.3"},
        )
        try:
            with urllib.request.urlopen(request, timeout=700) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            reason = exc.code
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            ConnectionError,
            TimeoutError,
        ) as exc:
            if attempt == attempts - 1:
                raise
            reason = type(exc).__name__
        wait = 30 * (attempt + 1)
        print(f"  {server} failed ({reason}); retrying in {wait} s", flush=True)
        time.sleep(wait)


def cached(name, query, attempts=6):
    """One Overpass request, saved under runtime/drainage/raw so an interrupted build resumes where it stopped."""
    path = RAW / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    print(f"Querying Overpass: {name}…", flush=True)
    payload = overpass(query, attempts)
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    time.sleep(10)  # be polite to the shared public servers between requests
    return payload


def split(box):
    south, west, north, east = (float(x) for x in box.split(","))
    my, mx = (south + north) / 2, (west + east) / 2
    return [
        f"{a:.5f},{b:.5f},{c:.5f},{d:.5f}"
        for a, c in ((south, my), (my, north))
        for b, d in ((west, mx), (mx, east))
    ]


def building_tile(name, box, depth=0):
    """A dense tile the servers cannot answer in one go is split into four, up to three times."""
    if (RAW / f"{name}.json").exists() or depth >= 3:
        return cached(name, QUERIES["buildings"].format(box=box))["elements"]
    try:
        return cached(name, QUERIES["buildings"].format(box=box), attempts=3)[
            "elements"
        ]
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        ConnectionError,
        TimeoutError,
    ):
        print(f"  splitting {name} into four smaller tiles", flush=True)
        return [
            e
            for k, sub in enumerate(split(box))
            for e in building_tile(f"{name}_{k}", sub, depth + 1)
        ]


GEOFABRIK = "https://download.geofabrik.de/africa/kenya-latest.osm.pbf"


def download(url, path):
    """Stream a large file to disk, resuming a partial download."""
    path.parent.mkdir(parents=True, exist_ok=True)
    have = path.stat().st_size if path.exists() else 0
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "xpat-nairobi-flood-hackathon/0.3",
            **({"Range": f"bytes={have}-"} if have else {}),
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return path  # already complete
        raise
    with response, open(path, "ab" if have and response.status == 206 else "wb") as out:
        total = int(response.headers.get("Content-Length") or 0) + (
            have if response.status == 206 else 0
        )
        done, step = (have if response.status == 206 else 0), 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if done // (25 << 20) > step:
                step = done // (25 << 20)
                print(f"  {done / 1e6:,.0f} of {total / 1e6:,.0f} MB", flush=True)
    return path


def from_pbf(path):
    """Drains, culverts and building centroids inside the Nairobi box, read from an OSM .pbf extract with pyosmium."""
    import osmium

    south, west, north, east = (float(x) for x in BBOX.split(","))
    inside = lambda lon, lat: west <= lon <= east and south <= lat <= north
    out = {"drains": [], "culverts": [], "buildings": []}

    class Handler(osmium.SimpleHandler):
        def way(self, w):
            tags = w.tags
            wanted = (
                tags.get("waterway") in ("drain", "ditch")
                or tags.get("tunnel") == "culvert"
                or "building" in tags
            )
            if not wanted:
                return
            try:
                pts = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
            except osmium.InvalidLocationError:
                return
            if len(pts) < 2 or not any(inside(*p) for p in pts):
                return
            line = [[round(x, 7), round(y, 7)] for x, y in pts]
            if tags.get("waterway") in ("drain", "ditch"):
                out["drains"].append(line)
            if tags.get("tunnel") == "culvert":
                out["culverts"].append(line[len(line) // 2])
            if "building" in tags:
                ring = pts[:-1] if pts[0] == pts[-1] and len(pts) > 2 else pts
                out["buildings"].append(
                    [
                        round(sum(p[0] for p in ring) / len(ring), 7),
                        round(sum(p[1] for p in ring) / len(ring), 7),
                    ]
                )

    Handler().apply_file(str(path), locations=True, idx="flex_mem")
    return out


def lines(payload):
    return [
        [[p["lon"], p["lat"]] for p in e["geometry"]]
        for e in payload.get("elements", [])
        if len(e.get("geometry") or []) >= 2
    ]


def midpoints(payload):
    out = []
    for line in lines(payload):
        out.append(line[len(line) // 2])
    return out


def centres(payload):
    return [
        [e["center"]["lon"], e["center"]["lat"]]
        for e in payload.get("elements", [])
        if e.get("center")
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--from-dir",
        help="Directory holding drains.json, culverts.json and buildings.json saved from Overpass",
    )
    parser.add_argument(
        "--geofabrik",
        action="store_true",
        help="Download the Kenya extract from Geofabrik and cut Nairobi locally (needs osmium)",
    )
    parser.add_argument("--output", default=str(OUT))
    args = parser.parse_args()
    if args.geofabrik:
        pbf = download(GEOFABRIK, RAW / "kenya-latest.osm.pbf")
        print(
            "Reading drains, culverts and buildings inside the Nairobi box…", flush=True
        )
        layers = {
            **from_pbf(pbf),
            "source": f"OpenStreetMap contributors (ODbL) via the Geofabrik Kenya extract ({GEOFABRIK})",
            "fetched": date.today().isoformat(),
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(layers))
        tmp.replace(out)  # readers never see a half-written file
        print(
            f"Wrote {out}: {len(layers['drains'])} drain lines, {len(layers['culverts'])} culverts, {len(layers['buildings'])} buildings"
        )
        return
    payloads = {}
    for name, query in QUERIES.items():
        if args.from_dir:
            payloads[name] = json.loads(
                (Path(args.from_dir) / f"{name}.json").read_text()
            )
        elif name == "buildings":
            payloads[name] = {
                "elements": [
                    e
                    for k, box in enumerate(tiles())
                    for e in building_tile(f"buildings_{k:02d}", box)
                ]
            }
        else:
            payloads[name] = cached(name, query)
    layers = {
        "drains": lines(payloads["drains"]),
        "culverts": midpoints(payloads["culverts"]),
        "buildings": centres(payloads["buildings"]),
        "source": "OpenStreetMap contributors (ODbL) via the Overpass API",
        "fetched": date.today().isoformat(),
        "queries": QUERIES,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(layers))
    tmp.replace(out)  # readers never see a half-written file
    print(
        f"Wrote {out}: {len(layers['drains'])} drain lines, {len(layers['culverts'])} culverts, {len(layers['buildings'])} buildings"
    )


if __name__ == "__main__":
    main()
