import math
from .constants import NAIROBI_BOUNDS


def in_coverage(lon, lat):
    west, south, east, north = NAIROBI_BOUNDS
    return west <= lon < east and south < lat <= north


def distance_m(lat1, lon1, lat2, lon2):
    a, b = map(math.radians, (lat1, lat2))
    dlat = b - a
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, h)))


def grid_cell(lat, lon, size_m):
    # Local equirectangular grid anchored on Nairobi extent, not administrative boundaries.
    x = (lon - 36.6) * 111195.08 * math.cos(math.radians(-1.275))
    y = (lat + 1.45) * 111195.08
    return f"grid-{math.floor(x / size_m)}-{math.floor(y / size_m)}"
