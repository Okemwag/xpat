"""Satellite flood check (AI enhancement 3): score the hazard maps against water seen by radar after a real event.

Input: a flood-extent GeoTIFF (1 = flooded, 0 = dry, nodata = not observed) made with the UN-SPIDER Recommended Practice
"Flood Mapping and Damage Assessment Using Sentinel-1 SAR Data in Google Earth Engine": VH backscatter after ÷ before the
event, flooded where the ratio exceeds 1.25, permanent water (JRC GSW > 10 months/yr) and slopes over 5% masked, specks of
≤ 8 connected pixels removed. ``scripts/gee_sentinel1_flood.js`` exports it for Nairobi (e.g. March–May 2024).

The flood map is REAL (observed); the comparison is PROXY. The method is change detection, not AI: it is an independent test
of the AI hazard adjustments, and its flooded pixels can be offered to the drainage model as extra training positives.

Limitation stated by UN-SPIDER: water among buildings is hard to detect with radar, so urban flooding is underestimated.
Read the result mainly along the Nairobi, Ngong and Mathare river corridors; a missed street flood is not a model hit or miss.
"""
from types import SimpleNamespace
import numpy as np
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.geo import in_coverage

class FloodExtent:
    def __init__(self, flooded, observed, transform, crs):
        self.flooded, self.observed, self.transform, self.crs = flooded, observed, transform, crs

    @classmethod
    def read(cls, source):
        """``source``: a path or the bytes of an uploaded GeoTIFF."""
        import rasterio
        from rasterio.io import MemoryFile
        try:
            if isinstance(source, (bytes, bytearray)):
                with MemoryFile(bytes(source)) as memory, memory.open() as ds: return cls._from(ds)
            with rasterio.open(source) as ds: return cls._from(ds)
        except rasterio.errors.RasterioIOError:
            raise ModelError('invalid_raster', 'Not a readable GeoTIFF flood map') from None

    @classmethod
    def _from(cls, ds):
        if ds.crs is None or ds.count != 1: raise ModelError('invalid_raster', 'The flood map must be a single-band GeoTIFF with a coordinate system')
        band = ds.read(1, masked=True)
        values = np.unique(band.compressed())
        if not set(values.tolist()) <= {0, 1}: raise ModelError('invalid_raster', 'The flood map must hold 1 (flooded) and 0 (dry) only, with nodata elsewhere')
        observed = ~np.ma.getmaskarray(band)
        return cls(np.asarray(band.filled(0)) == 1, observed, ds.transform, ds.crs.to_string())

    def _lonlat(self, rows, cols):
        xs, ys = self.transform@(cols+.5, rows+.5)
        if self.crs != 'EPSG:4326':
            from rasterio.warp import transform as warp
            xs, ys = warp(self.crs, 'EPSG:4326', list(xs), list(ys))
        return np.asarray(ys, float), np.asarray(xs, float)

    def sample(self, flooded, n, seed):
        """Up to n seeded random pixel centres (lat, lon) that are flooded (or observed dry) and inside the hazard maps."""
        mask = self.observed & (self.flooded if flooded else ~self.flooded)
        rows, cols = np.nonzero(mask)
        if not len(rows): return []
        rng = np.random.default_rng(seed)
        pick = rng.permutation(len(rows))[:min(len(rows), n*4)]
        lats, lons = self._lonlat(rows[pick], cols[pick])
        return [(float(a), float(b)) for a, b in zip(lats, lons) if in_coverage(b, a)][:n]

    def summary(self):
        cell = abs(self.transform.a*self.transform.e)
        return {'observed_pixels': int(self.observed.sum()), 'flooded_pixels': int((self.flooded & self.observed).sum()), 'crs': self.crs,
                'pixel_size': [abs(self.transform.a), abs(self.transform.e)], 'pixel_area_units2': cell}

def _flagged(provider, points):
    counts = {t: 0 for t in TIERS}; any_tier = 0; scored = 0
    for lat, lon in points:
        scores = provider.scores(SimpleNamespace(lat=lat, lon=lon, hazard={}))
        if any(scores[t] is None for t in TIERS): continue
        scored += 1
        for t in TIERS: counts[t] += scores[t] > 0
        any_tier += any(scores[t] > 0 for t in TIERS)
    return scored, counts, any_tier

def compare(extent, provider, config, hotspots=()):
    """How much observed flooding the hazard maps flag, against how much observed dry ground they flag.

    hit rate = share of sampled flooded pixels with score > 0 · flag rate on dry ground = share of sampled dry pixels with score > 0.
    A useful map flags flooded pixels much more often than dry ones. Neither number is an accuracy.
    """
    s = config.satellite_check
    wet = extent.sample(True, s['sample_points'], s['seed']); dry = extent.sample(False, s['sample_points'], s['seed']+1)
    if not wet: raise ModelError('no_flooding', 'The flood map shows no flooded pixels inside the hazard maps')
    n_wet, wet_by_tier, wet_any = _flagged(provider, wet)
    n_dry, dry_by_tier, dry_any = _flagged(provider, dry)
    rate = lambda k, n: round(100*k/n, 1) if n else None
    near = []
    if hotspots:
        inv = ~extent.transform
        for h in hotspots:
            x, y = h.lon, h.lat
            if extent.crs != 'EPSG:4326':
                from rasterio.warp import transform as warp
                xs, ys = warp('EPSG:4326', extent.crs, [x], [y]); x, y = xs[0], ys[0]
            col, row = inv@(x, y); r, c = int(np.floor(row)), int(np.floor(col))
            if not (0 <= r < extent.flooded.shape[0] and 0 <= c < extent.flooded.shape[1]):
                near.append({'name': h.name, 'flooded_nearby': None}); continue
            # Within 10 pixels of the geocoded centre (≈100 m at Sentinel-1's 10 m pixels).
            window = extent.flooded[max(0, r-10):r+11, max(0, c-10):c+11] & extent.observed[max(0, r-10):r+11, max(0, c-10):c+11]
            near.append({'name': h.name, 'flooded_nearby': bool(window.any())})
    return {'flooded_points': n_wet, 'dry_points': n_dry,
            'hit_rate_pct': {t: rate(wet_by_tier[t], n_wet) for t in TIERS}, 'hit_rate_any_pct': rate(wet_any, n_wet),
            'dry_flag_rate_pct': {t: rate(dry_by_tier[t], n_dry) for t in TIERS}, 'dry_flag_rate_any_pct': rate(dry_any, n_dry),
            'hotspots_with_observed_water': near, 'extent': extent.summary(), 'seed': s['seed'],
            'labels': {'flood_map': 'REAL', 'comparison': 'PROXY'},
            'caveats': ['Radar under-detects water among buildings (UN-SPIDER), so street flooding in dense areas is often missing from the map.',
                        'One event is one sample of weather; a pixel that stayed dry this time can still flood.',
                        'Hit rate and dry-ground flag rate are not accuracy; read them together.']}

def training_points(extent, config, n=None):
    """Flooded pixel centres for the drainage model (positives), seeded."""
    s = config.satellite_check
    return extent.sample(True, n or s['sample_points'], s['seed']+2)
