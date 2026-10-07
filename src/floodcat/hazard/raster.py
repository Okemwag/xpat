from contextlib import ExitStack
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import bounded

class RasterHazard:
    """Context-managed local GeoTIFF sampler; CRS conversion, bounds and masks checked."""
    def __init__(self, directory):
        self.directory=directory
        self.stack=ExitStack()
        self.datasets={}
    def __enter__(self):
        from pathlib import Path
        import rasterio
        try:
            for tier in TIERS:
                ds=self.stack.enter_context(rasterio.open(Path(self.directory)/f'nairobi_pluvial_proxy_{tier}.tif'))
                if ds.crs is None or ds.count!=1:
                    raise ModelError("invalid_raster", "Single-band raster with CRS required")
                self.datasets[tier]=ds
        except Exception:
            self.stack.close(); raise
        return self
    def __exit__(self,*args): self.stack.close()
    def scores(self,asset):
        from rasterio.warp import transform
        result={}
        for tier,ds in self.datasets.items():
            x,y=transform('EPSG:4326',ds.crs,[asset.lon],[asset.lat])
            col,row=x[0],y[0]
            r,c=ds.index(col,row)
            if not (0<=r<ds.height and 0<=c<ds.width):
                result[tier]=None; continue
            value=next(ds.sample([(col,row)],masked=True))[0]
            if getattr(value,'mask',False): result[tier]=None
            else: result[tier]=bounded(float(value),f'raster_{tier}')
        return result
