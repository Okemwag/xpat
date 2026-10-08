"""Building attributes from imagery (AI enhancement 4): storeys from Open Buildings 2.5D Temporal heights.

Open Buildings 2.5D Temporal v1 (Google Research; Earth Engine GOOGLE/Research/open-buildings-temporal/v1) gives building
height in metres above terrain (0–100 m, yearly 2016–2023, ~4 m effective resolution, CC-BY 4.0 or ODbL). The heights come
from a machine-learning model on Sentinel-2 imagery, so every value filled here is labelled AI; the catalogue publishes no
height accuracy. ``scripts/gee_open_buildings_height.js`` exports the Nairobi raster.

Only blank ``floors_above_ground`` values are proposed; the user accepts or rejects each one; accepted rows pass the same
validation as any CSV. Storeys = round(height ÷ storey_height_m), at least 1 (ASSUMPTION). Housing class is never inferred.
Storey counts change loss through ``storey_exposure`` (financial/loss.exposed_fraction).
"""
import math
import numpy as np
from ..core.errors import ModelError
from ..core.numeric import finite

class HeightRaster:
    def __init__(self, heights, valid, transform, crs):
        self.heights, self.valid, self.transform, self.crs = heights, valid, transform, crs

    @classmethod
    def read(cls, source):
        import rasterio
        from rasterio.io import MemoryFile
        try:
            if isinstance(source, (bytes, bytearray)):
                with MemoryFile(bytes(source)) as memory, memory.open() as ds: return cls._from(ds)
            with rasterio.open(source) as ds: return cls._from(ds)
        except rasterio.errors.RasterioIOError:
            raise ModelError('invalid_raster', 'Not a readable GeoTIFF of building heights') from None

    @classmethod
    def _from(cls, ds):
        if ds.crs is None or ds.count != 1: raise ModelError('invalid_raster', 'The height map must be a single-band GeoTIFF with a coordinate system')
        if ds.crs.to_string() != 'EPSG:4326': raise ModelError('invalid_raster', 'Export the height map in EPSG:4326 (see scripts/gee_open_buildings_height.js)')
        band = ds.read(1, masked=True).astype(float)
        heights = np.asarray(band.filled(np.nan))
        if np.nanmax(heights, initial=0) > 150: raise ModelError('invalid_raster', 'Heights above 150 m found; is this a height map in metres?')
        return cls(heights, np.isfinite(heights), ds.transform, ds.crs.to_string())

    def height_at(self, lat, lon, radius_m):
        """Tallest building height within radius_m of the point (m), or None where the map has no data."""
        col, row = ~self.transform@(lon, lat)
        dy = radius_m/111195.08/abs(self.transform.e); dx = radius_m/(111195.08*math.cos(math.radians(lat)))/abs(self.transform.a)
        r0, r1 = int(math.floor(row-dy)), int(math.floor(row+dy))+1; c0, c1 = int(math.floor(col-dx)), int(math.floor(col+dx))+1
        rows, cols = self.heights.shape
        if r1 <= 0 or c1 <= 0 or r0 >= rows or c0 >= cols: return None
        window = self.heights[max(0, r0):min(rows, r1), max(0, c0):min(cols, c1)]
        if not np.isfinite(window).any(): return None
        return float(np.nanmax(window))

def _blank(value):
    return value is None or str(value).strip() == ''

def propose_floors(rows, heights, config):
    """One proposal per row with blank floors_above_ground and usable coordinates. Never changes the rows."""
    b = config.building_attributes
    proposals = []
    for index, row in enumerate(rows):
        if not _blank(row.get('floors_above_ground')): continue
        try: lat, lon = finite(row.get('lat'), 'lat'), finite(row.get('lon'), 'lon')
        except ModelError: continue
        height = heights.height_at(lat, lon, b['search_radius_m'])
        base = {'row': index, 'loc_id': str(row.get('loc_id') or f'row {index+1}'), 'height_m': None if height is None else round(height, 1)}
        if height is None:
            proposals.append({**base, 'floors': None, 'status': 'no_data', 'reason': 'The height map has no data here'}); continue
        if height < b['min_building_height_m']:
            proposals.append({**base, 'floors': None, 'status': 'no_building',
                              'reason': f"No building taller than {b['min_building_height_m']:g} m detected within {b['search_radius_m']:g} m; check the coordinates"}); continue
        floors = int(min(b['max_floors'], max(1, round(height/b['storey_height_m']))))
        proposals.append({**base, 'floors': floors, 'status': 'proposed',
                          'reason': f"Open Buildings height {height:.1f} m ÷ {b['storey_height_m']:g} m per storey ≈ {floors} storey(s)"})
    return proposals

def apply_floors(rows, proposals, accepted_rows):
    """Copy rows, filling floors_above_ground for accepted proposals and recording why in ai_field_provenance."""
    accepted = {p['row']: p for p in proposals if p['status'] == 'proposed' and p['row'] in set(accepted_rows)}
    out = []
    for index, row in enumerate(rows):
        row = dict(row)
        if index in accepted:
            p = accepted[index]
            row['floors_above_ground'] = str(p['floors'])
            note = f"floors_above_ground: AI (Open Buildings 2.5D height {p['height_m']:g} m; storey height ASSUMPTION)"
            row['ai_field_provenance'] = '; '.join(x for x in (row.get('ai_field_provenance') or '', note) if x)
        out.append(row)
    return out
