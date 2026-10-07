from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
rasterio=pytest.importorskip('rasterio')
from rasterio.transform import from_origin
from floodcat.hazard.raster import RasterHazard
from floodcat.core.constants import TIERS

def test_raster_zero_mask_outside_and_crs(tmp_path):
    for i,t in enumerate(TIERS):
        values=np.array([[0.,.1*(i+1)],[.2,-9999]],dtype='float32')
        with rasterio.open(tmp_path/f'nairobi_pluvial_proxy_{t}.tif','w',driver='GTiff',height=2,width=2,count=1,
                           dtype='float32',crs='EPSG:4326',transform=from_origin(36.6,-1.1,.1,.1),nodata=-9999) as ds:
            ds.write(values,1)
    with RasterHazard(tmp_path) as provider:
        assert all(v==0 for v in provider.scores(SimpleNamespace(lon=36.65,lat=-1.15)).values())
        assert provider.scores(SimpleNamespace(lon=36.75,lat=-1.15))['common']==pytest.approx(.5)
        assert all(v is None for v in provider.scores(SimpleNamespace(lon=36.75,lat=-1.25)).values())
        assert all(v is None for v in provider.scores(SimpleNamespace(lon=37.02,lat=-1.2)).values())
