import math
from pathlib import Path
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import bounded


def masked_value():
    import numpy

    return numpy.ma.masked


class RasterHazard:
    """Five proxy GeoTIFFs held in memory: thread-safe lookups, no open file handles after load.

    A cell is found with the same floor rule as rasterio's index(). Points off the grid or on
    masked cells return None so the caller rejects them instead of assuming zero hazard.
    """

    def __init__(self, directory):
        self.directory = Path(directory)
        self.grids = {}

    def load(self):
        import rasterio

        for tier in TIERS:
            path = self.directory / f"nairobi_pluvial_proxy_{tier}.tif"
            if not path.exists():
                raise ModelError("missing_raster", f"Hazard map not found: {path.name}")
            with rasterio.open(path) as ds:
                if ds.crs is None or ds.count != 1:
                    raise ModelError(
                        "invalid_raster", "Single-band raster with CRS required"
                    )
                self.grids[tier] = (
                    ds.read(1, masked=True),
                    ds.transform,
                    ds.crs.to_string(),
                    ds.height,
                    ds.width,
                )
        return self

    def __enter__(self):
        return self.load() if not self.grids else self

    def __exit__(self, *args):
        pass

    def scores(self, asset):
        if not self.grids:
            self.load()
        result = {}
        for tier, (array, transform, crs, height, width) in self.grids.items():
            x, y = asset.lon, asset.lat
            if crs != "EPSG:4326":
                from rasterio.warp import transform as warp

                xs, ys = warp("EPSG:4326", crs, [x], [y])
                x, y = xs[0], ys[0]
            col, row = ~transform @ (x, y)
            r, c = math.floor(row), math.floor(col)
            if not (0 <= r < height and 0 <= c < width):
                result[tier] = None
                continue
            value = array[r, c]
            if value is masked_value():
                result[tier] = None
                continue
            result[tier] = bounded(float(value), f"raster_{tier}")
        return result
