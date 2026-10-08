"""Find Nairobi place names in report text with an offline OpenStreetMap gazetteer (no LLM, no network).

The gazetteer (outputs/nairobi_places.json, scripts/build_places.py) holds named OSM places; the county hotspot list is
not an input. Matching is deterministic: whole words, flexible apostrophes, spaces and hyphens, the first letter must be
a capital (so "harambee" the word does not match Harambee the estate), longest name wins. Names used for more than one
place far apart are dropped as ambiguous rather than guessed.
"""

import json
import re
from pathlib import Path
from ..core.errors import ModelError
from ..core.geo import distance_m

# Lower = broader. Broader places win when the same name is mapped at several levels.
RANK = {"suburb": 1, "town": 1, "quarter": 2, "neighbourhood": 3, "village": 3, "locality": 4, "hamlet": 4}


def norm(name):
    return " ".join(re.sub(r"['’`\-]", " ", str(name)).lower().replace("  ", " ").split()).replace(" ", "")


def _pattern(name):
    """Whole name with an optional apostrophe between any two letters and flexible spaces or hyphens between words."""
    words = [re.sub(r"['’`]", "", w) for w in re.split(r"[\s\-]+", name.strip()) if w]
    return r"[\s\-]*".join("['’`]?".join(re.escape(ch) for ch in w) for w in words if w)


class PlaceIndex:
    def __init__(self, places, ignore=(), ambiguity_m=3000.0, not_before=()):
        ignore = {norm(n) for n in ignore}
        # "Ngong River", "Langata Road": a feature named after a place, often far from it.
        self._not_before = re.compile(r"\s+(?:" + "|".join(re.escape(w) for w in not_before) + r")\b", re.IGNORECASE) if not_before else None
        groups = {}
        for p in places:
            if p.get("place") not in RANK:
                continue
            for name in [p["name"], *p.get("alt_names", [])]:
                key = norm(name)
                if len(key) < 3 or key in ignore:
                    continue
                groups.setdefault(key, {"names": set(), "places": []})
                groups[key]["names"].add(name)
                groups[key]["places"].append(p)
        self.entries, self.ambiguous = {}, []
        for key, g in groups.items():
            best = min(RANK[p["place"]] for p in g["places"])
            top = {(p["lat"], p["lon"]): p for p in g["places"] if RANK[p["place"]] == best}
            pts = list(top.values())
            if any(distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) > ambiguity_m for a in pts for b in pts):
                self.ambiguous.append(sorted(g["names"])[0])
                continue
            lat = sum(p["lat"] for p in pts) / len(pts)
            lon = sum(p["lon"] for p in pts) / len(pts)
            self.entries[key] = {"name": pts[0]["name"], "lat": lat, "lon": lon, "place": pts[0]["place"],
                                 "osm": pts[0].get("osm"), "variants": sorted(g["names"])}
        variants = sorted({v for e in self.entries.values() for v in e["variants"]}, key=len, reverse=True)
        self._regex = re.compile(r"(?<![\w'’])(" + "|".join(_pattern(v) for v in variants) + r")(?![\w'’])",
                                 re.IGNORECASE) if variants else None

    @classmethod
    def load(cls, path, ignore=(), ambiguity_m=3000.0, not_before=()):
        path = Path(path)
        if not path.exists():
            raise ModelError("missing_gazetteer", f"Place list not found: {path.name}. Build it with `make places`")
        return cls(json.loads(path.read_text())["places"], ignore, ambiguity_m, not_before)

    def find(self, text):
        """Places named in `text`: [{name, lat, lon, place, start, end, matched}], each place once (first mention)."""
        if not self._regex:
            return []
        seen, out = set(), []
        for m in self._regex.finditer(text):
            if not m.group(1)[0].isupper():
                continue
            if self._not_before and self._not_before.match(text, m.end(1)):
                continue
            entry = self.entries.get(norm(m.group(1)))
            if entry is None or entry["name"] in seen:
                continue
            seen.add(entry["name"])
            out.append({**{k: entry[k] for k in ("name", "lat", "lon", "place", "osm")}, "start": m.start(1),
                        "end": m.end(1), "matched": m.group(1)})
        return out
