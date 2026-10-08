"""Build the OSM drainage layers used by the drainage-aware hazard (hazard/drainage.py).

Usage:
    uv run python scripts/build_drainage_layers.py                       # query the Overpass API (network; resumable)
    uv run python scripts/build_drainage_layers.py --from-dir saved/     # convert saved Overpass JSON files (offline)

Writes runtime/drainage/osm_layers.json (gitignored; regenerate on each server). Contents:
  drains    — ways tagged waterway=drain or waterway=ditch, as [lon, lat] lines
  culverts  — midpoints of ways tagged tunnel=culvert
  buildings — centroids of ways tagged building=*
Data © OpenStreetMap contributors, ODbL. OSM drain mapping is uneven across Nairobi; see docs/AI_ENHANCEMENTS.md.
"""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'runtime'/'drainage'/'osm_layers.json'
OVERPASS = 'https://overpass-api.de/api/interpreter'
BBOX = '-1.45,36.60,-1.10,37.00'  # south, west, north, east (configs: NAIROBI_BOUNDS)
TILES = 4  # buildings are fetched in TILES × TILES boxes so no single request is too large for the public server
QUERIES = {
    'drains': f'[out:json][timeout:300];way["waterway"~"^(drain|ditch)$"]({BBOX});out geom;',
    'culverts': f'[out:json][timeout:300];way["tunnel"="culvert"]({BBOX});out geom;',
    'buildings': '[out:json][timeout:600];way["building"]({box});out center qt;',
}
RAW = ROOT/'runtime'/'drainage'/'raw'

def tiles():
    south, west, north, east = (float(x) for x in BBOX.split(','))
    dy, dx = (north-south)/TILES, (east-west)/TILES
    return [f'{south+i*dy:.4f},{west+j*dx:.4f},{south+(i+1)*dy:.4f},{west+(j+1)*dx:.4f}' for i in range(TILES) for j in range(TILES)]

def overpass(query, attempts=5):
    for attempt in range(attempts):
        request = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({'data': query}).encode(),
                                         headers={'User-Agent': 'xpat-nairobi-flood-hackathon/0.3'})
        try:
            with urllib.request.urlopen(request, timeout=700) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt == attempts-1: raise
            reason = exc.code
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if attempt == attempts-1: raise
            reason = type(exc).__name__
        wait = 30*(attempt+1); print(f'  server busy ({reason}); retrying in {wait} s', flush=True); time.sleep(wait)

def cached(name, query):
    """One Overpass request, saved under runtime/drainage/raw so an interrupted build resumes where it stopped."""
    path = RAW/f'{name}.json'
    if path.exists(): return json.loads(path.read_text())
    print(f'Querying Overpass: {name}…', flush=True)
    payload = overpass(query)
    RAW.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload))
    return payload

def lines(payload):
    return [[[p['lon'], p['lat']] for p in e['geometry']] for e in payload.get('elements', []) if len(e.get('geometry') or []) >= 2]

def midpoints(payload):
    out = []
    for line in lines(payload):
        out.append(line[len(line)//2])
    return out

def centres(payload):
    return [[e['center']['lon'], e['center']['lat']] for e in payload.get('elements', []) if e.get('center')]

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--from-dir', help='Directory holding drains.json, culverts.json and buildings.json saved from Overpass')
    parser.add_argument('--output', default=str(OUT))
    args = parser.parse_args()
    payloads = {}
    for name, query in QUERIES.items():
        if args.from_dir:
            payloads[name] = json.loads((Path(args.from_dir)/f'{name}.json').read_text())
        elif name == 'buildings':
            parts = [cached(f'buildings_{k:02d}', query.format(box=box)) for k, box in enumerate(tiles())]
            payloads[name] = {'elements': [e for p in parts for e in p.get('elements', [])]}
        else:
            payloads[name] = cached(name, query)
    layers = {'drains': lines(payloads['drains']), 'culverts': midpoints(payloads['culverts']), 'buildings': centres(payloads['buildings']),
              'source': 'OpenStreetMap contributors (ODbL) via the Overpass API', 'fetched': date.today().isoformat(),
              'queries': QUERIES}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layers))
    print(f"Wrote {out}: {len(layers['drains'])} drain lines, {len(layers['culverts'])} culverts, {len(layers['buildings'])} buildings")

if __name__ == '__main__':
    main()
