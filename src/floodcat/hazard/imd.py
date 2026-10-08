"""Infrastructure & Maintenance Deficit index (IMD): a runoff-pressure proxy from OpenStreetMap building footprints.

Why: the terrain proxy flags 12 of 24 named flood areas. The misses flood when rain on built-up ground exceeds what
the drains carry, which terrain cannot see. Dense, mostly roofed ground produces more runoff, faster, and in Nairobi
is where drains are most often undersized, blocked or missing. We cannot observe drains, so the index measures the
pressure side only:

  built fraction  = building footprint area / ground area, within a circular window   (impervious-surface proxy)
  density         = buildings per hectare, within the same window

Each is scaled to 0–1 between two thresholds set in config *before* checking against the hotspots (ASSUMPTION), and
combined with config weights. The index is PROXY data: it never measures drainage condition or maintenance, roads and
paved yards are not counted, and OSM mapping completeness varies by neighbourhood (an unmapped area reads as empty).

The index raises hazard scores the same way approved evidence does: s' = 1 - (1 - s)(1 - w·f_tier·I). Tier factors
grow toward the rarest tier, so adjusted scores keep their extreme→common order.
"""

import math
from pathlib import Path
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import bounded

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQ = 111_320.0
BANDS = ("built_fraction", "buildings_per_ha")
# Evaluation only (not a model parameter): "built-up" ground for the chance baseline, set below the sparsest named
# hotspot (≈4 buildings/ha) so every hotspot counts as built-up; and the index below which a hit is reported as marginal.
BUILT_UP_PER_HA = 2.0
MARGINAL_INDEX = 0.05


# Footprint geometry (pure) -----------------------------------------------------------------------------------
def footprint(ring):
    """Area (m²) and centroid (lat, lon) of a closed lat/lon ring, on a local equirectangular projection.

    Error is well under 1% at building scale near the equator. Returns None for degenerate rings.
    """
    pts = [(p["lat"], p["lon"]) if isinstance(p, dict) else tuple(p) for p in ring]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    lat0 = sum(p[0] for p in pts) / len(pts)
    lon0 = sum(p[1] for p in pts) / len(pts)
    kx = M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))
    xy = [((lon - lon0) * kx, (lat - lat0) * M_PER_DEG_LAT) for lat, lon in pts]
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return None
    a /= 2
    cx, cy = cx / (6 * a), cy / (6 * a)
    return abs(a), (lat0 + cy / M_PER_DEG_LAT, lon0 + cx / kx)


# Grid ---------------------------------------------------------------------------------------------------------
class Grid:
    """North-up lat/lon grid: origin at the top-left corner, square cells of `cell_deg` degrees."""

    def __init__(self, west, north, cell_deg, width, height):
        self.west, self.north, self.cell_deg = float(west), float(north), float(cell_deg)
        self.width, self.height = int(width), int(height)

    @classmethod
    def covering(cls, west, south, east, north, cell_deg):
        return cls(
            west,
            north,
            cell_deg,
            math.ceil(round((east - west) / cell_deg, 9)),
            math.ceil(round((north - south) / cell_deg, 9)),
        )

    def index(self, lat, lon):
        """(row, col) with the same floor rule as rasterio's index(), or None off the grid."""
        r = math.floor((self.north - lat) / self.cell_deg)
        c = math.floor((lon - self.west) / self.cell_deg)
        return (r, c) if 0 <= r < self.height and 0 <= c < self.width else None

    def cell_size_m(self):
        lat = self.north - self.height * self.cell_deg / 2
        return (
            self.cell_deg * M_PER_DEG_LON_EQ * math.cos(math.radians(lat)),
            self.cell_deg * M_PER_DEG_LAT,
        )

    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(self.west, self.north, self.cell_deg, self.cell_deg)


def accumulate(buildings, grid, area=None, count=None):
    """Add (area_m2, (lat, lon)) footprints to per-cell area and count arrays, by centroid."""
    import numpy as np

    area = np.zeros((grid.height, grid.width)) if area is None else area
    count = np.zeros((grid.height, grid.width)) if count is None else count
    for a, (lat, lon) in buildings:
        rc = grid.index(lat, lon)
        if rc:
            area[rc] += a
            count[rc] += 1
    return area, count


def window_sum(array, radius_cells_x, radius_cells_y):
    """Sum over an elliptical window (circular on the ground); cells beyond the grid edge count as empty."""
    import numpy as np

    rx, ry = int(radius_cells_x), int(radius_cells_y)
    out = np.zeros_like(array, dtype=float)
    padded = np.pad(array.astype(float), ((ry, ry), (rx, rx)))
    h, w = array.shape
    n = 0
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if (dx / max(radius_cells_x, 1e-9)) ** 2 + (dy / max(radius_cells_y, 1e-9)) ** 2 <= 1 + 1e-9:
                out += padded[ry + dy : ry + dy + h, rx + dx : rx + dx + w]
                n += 1
    return out, n


def neighbourhood(area, count, grid, radius_m):
    """Built fraction and buildings per hectare within `radius_m` of each cell centre."""
    cw, ch = grid.cell_size_m()
    if radius_m < max(cw, ch) / 2:
        raise ModelError("invalid_config", "IMD window radius must be at least half a grid cell")
    area_sum, n = window_sum(area, radius_m / cw, radius_m / ch)
    count_sum, _ = window_sum(count, radius_m / cw, radius_m / ch)
    window_m2 = n * cw * ch
    return {"built_fraction": (area_sum / window_m2).clip(0, 1), "buildings_per_ha": count_sum / (window_m2 / 10_000)}


# Index (pure) -------------------------------------------------------------------------------------------------
def scale(value, low, high):
    """0 at or below `low`, 1 at or above `high`, linear between."""
    return min(1.0, max(0.0, (value - low) / (high - low)))


def index_value(components, settings):
    """IMD in [0, 1] from the raw neighbourhood components and the config thresholds and weights."""
    w = settings["component_weights"]
    total = sum(w.values())
    parts = {
        "built_fraction": scale(components["built_fraction"], *settings["built_fraction_range"]),
        "buildings_per_ha": scale(components["buildings_per_ha"], *settings["density_per_ha_range"]),
    }
    return sum(w[k] * parts[k] for k in parts) / total, parts


def uplift(scores, index, settings):
    """s' = 1 - (1 - s)(1 - w·f_tier·I) for every tier; returns validated scores."""
    from .interpretation import validate_scores

    index = bounded(index, "imd_index")
    if index == 0:
        return validate_scores(dict(scores))
    w, f = settings["weight"], settings["tier_factors"]
    return validate_scores({t: max(scores[t], 1 - (1 - scores[t]) * (1 - w * f[t] * index)) for t in TIERS})


def validate_settings(s):
    """Raise ModelError unless the imd_index config block is complete and coherent."""
    need = {"enabled", "grid_path", "window_radius_m", "built_fraction_range", "density_per_ha_range",
            "component_weights", "weight", "tier_factors", "source"}
    if not isinstance(s, dict) or set(s) != need or not isinstance(s["enabled"], bool):
        raise ModelError("invalid_config", "imd_index needs " + ", ".join(sorted(need)))
    for key in ("built_fraction_range", "density_per_ha_range"):
        lo, hi = (float(x) for x in s[key])
        if not 0 <= lo < hi:
            raise ModelError("invalid_config", f"imd_index.{key} must be [low, high] with 0 ≤ low < high")
    bounded(s["built_fraction_range"][1], "built_fraction_range", 0, 1)
    if set(s["component_weights"]) != set(BANDS) or any(float(v) < 0 for v in s["component_weights"].values()) \
            or sum(float(v) for v in s["component_weights"].values()) <= 0:
        raise ModelError("invalid_config", "imd_index.component_weights needs non-negative built_fraction and buildings_per_ha")
    bounded(s["weight"], "imd_index.weight")
    if set(s["tier_factors"]) != set(TIERS):
        raise ModelError("invalid_config", "imd_index.tier_factors needs every tier")
    f = [bounded(s["tier_factors"][t], t) for t in TIERS]
    if any(a > b for a, b in zip(f, f[1:])):
        raise ModelError("invalid_config", "imd_index.tier_factors must increase from extreme to common")
    if float(s["window_radius_m"]) <= 0:
        raise ModelError("invalid_config", "imd_index.window_radius_m must be positive")
    return {**s, "window_radius_m": float(s["window_radius_m"]), "weight": float(s["weight"]),
            "built_fraction_range": tuple(float(x) for x in s["built_fraction_range"]),
            "density_per_ha_range": tuple(float(x) for x in s["density_per_ha_range"]),
            "component_weights": {k: float(v) for k, v in s["component_weights"].items()},
            "tier_factors": {t: float(s["tier_factors"][t]) for t in TIERS}}


# Runtime lookup -----------------------------------------------------------------------------------------------
class ImdGrid:
    """The built IMD component grid (GeoTIFF from scripts/build_imd_index.py), held in memory."""

    def __init__(self, bands, grid, meta=None):
        self.bands, self.grid, self.meta = bands, grid, meta or {}

    @classmethod
    def load(cls, path):
        import rasterio

        path = Path(path)
        if not path.exists():
            raise ModelError("missing_imd_grid", f"IMD grid not found: {path}. Build it with `make imd-index`")
        with rasterio.open(path) as ds:
            if ds.count != len(BANDS) or ds.crs is None or ds.crs.to_string() != "EPSG:4326":
                raise ModelError("invalid_imd_grid", "IMD grid must have 2 bands in EPSG:4326")
            t = ds.transform
            if abs(t.a + t.e) > 1e-12:
                raise ModelError("invalid_imd_grid", "IMD grid cells must be square in degrees")
            bands = {name: ds.read(i + 1) for i, name in enumerate(BANDS)}
            grid = Grid(t.c, t.f, t.a, ds.width, ds.height)
            return cls(bands, grid, dict(ds.tags()))

    def components(self, lat, lon):
        rc = self.grid.index(lat, lon)
        if rc is None:
            raise ModelError("imd_unavailable", "Location is outside the infrastructure-deficit grid")
        return {k: float(v[rc]) for k, v in self.bands.items()}

    def index(self, lat, lon, settings):
        value, parts = index_value(self.components(lat, lon), settings)
        return value

    def share_flagged(self, settings, mask=None):
        """Share of grid cells (optionally within `mask`) with an index above zero: how much of the city it touches."""
        import numpy as np

        w = settings["component_weights"]
        parts = []
        for band, key in (("built_fraction", "built_fraction_range"), ("buildings_per_ha", "density_per_ha_range")):
            lo, hi = settings[key]
            parts.append(w[band] * np.clip((self.bands[band] - lo) / (hi - lo), 0, 1))
        idx = sum(parts) / sum(w.values())
        cells = idx if mask is None else idx[mask]
        return float((cells > 0).mean()), idx


# Validation against the named hotspots -------------------------------------------------------------------------
def hotspot_comparison(hotspots, provider, imd, settings):
    """Named-hotspot hit rate with terrain only and with the index, using the same rule (any tier score > 0).

    A higher hit rate alone proves little: an index that flags the whole city flags every hotspot. Read it together
    with `map_share_flagged` from `area_comparison`.
    """
    from types import SimpleNamespace

    points = []
    for h in hotspots:
        terrain = provider.scores(SimpleNamespace(lat=h.lat, lon=h.lon, hazard={}))
        if any(terrain[t] is None for t in TIERS):
            raise ModelError("hazard_unavailable", f"Hotspot {h.name} lies outside hazard coverage")
        comps = imd.components(h.lat, h.lon)
        index, parts = index_value(comps, settings)
        adjusted = uplift(terrain, index, settings)
        points.append({
            "name": h.name, "lat": h.lat, "lon": h.lon,
            "built_fraction": round(comps["built_fraction"], 4),
            "buildings_per_ha": round(comps["buildings_per_ha"], 1),
            "imd_index": round(index, 4),
            "terrain_flagged": any(terrain[t] > 0 for t in TIERS),
            "flagged_with_index": any(adjusted[t] > 0 for t in TIERS),
            "terrain_common": terrain["common"], "adjusted_common": round(adjusted["common"], 4),
        })
    before = sum(p["terrain_flagged"] for p in points)
    after = sum(p["flagged_with_index"] for p in points)
    new = [p for p in points if p["flagged_with_index"] and not p["terrain_flagged"]]
    return {
        "marginal_new": [p["name"] for p in new if p["imd_index"] < MARGINAL_INDEX],
        "marginal_index": MARGINAL_INDEX,
        "hotspot_count": len(points),
        "flagged_terrain_only": before,
        "flagged_with_index": after,
        "newly_flagged": [p["name"] for p in points if p["flagged_with_index"] and not p["terrain_flagged"]],
        "still_missed": [p["name"] for p in points if not p["flagged_with_index"]],
        "rule": "flagged when the score is above zero in any tier at the geocoded point",
        "points": points,
    }


def area_comparison(terrain_common, terrain_grid, imd, settings):
    """Share of the hazard-map area flagged (score > 0) with terrain only and with the index.

    `terrain_common` is the rarest-tier terrain array (masked or plain) and `terrain_grid` its Grid. Each terrain cell
    takes the index of the IMD cell containing its centre.
    """
    import numpy as np

    _, idx = imd.share_flagged(settings)
    rows = np.arange(terrain_grid.height)
    cols = np.arange(terrain_grid.width)
    lat = terrain_grid.north - (rows + 0.5) * terrain_grid.cell_deg
    lon = terrain_grid.west + (cols + 0.5) * terrain_grid.cell_deg
    r = np.floor((imd.grid.north - lat) / imd.grid.cell_deg).astype(int)
    c = np.floor((lon - imd.grid.west) / imd.grid.cell_deg).astype(int)
    inside_r = (r >= 0) & (r < imd.grid.height)
    inside_c = (c >= 0) & (c < imd.grid.width)
    sampled = np.zeros((terrain_grid.height, terrain_grid.width))
    sampled[np.ix_(inside_r, inside_c)] = idx[np.ix_(r[inside_r], c[inside_c])]
    valid = ~np.ma.getmaskarray(terrain_common)
    terrain = np.ma.getdata(terrain_common) > 0
    with_index = terrain | (sampled > 0)
    n = valid.sum()
    built_up = imd.bands["buildings_per_ha"] >= BUILT_UP_PER_HA
    return {
        "built_up_per_ha": BUILT_UP_PER_HA,
        "built_up_share_index_above_zero": float((idx[built_up] > 0).mean()) if built_up.any() else 0.0,
        "built_up_share_index_not_marginal": float((idx[built_up] >= MARGINAL_INDEX).mean()) if built_up.any() else 0.0,
        "cells": int(n),
        "share_flagged_terrain_only": float((terrain & valid).sum() / n),
        "share_flagged_with_index": float((with_index & valid).sum() / n),
        "share_index_above_zero": float(((sampled > 0) & valid).sum() / n),
    }
