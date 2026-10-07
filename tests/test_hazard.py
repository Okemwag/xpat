import pytest
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.exposure.validation import validate_rows
from floodcat.hazard.hotspots import hotspot_area, load_hotspots, nearest_hotspot, hotspot_check
from floodcat.hazard.interpretation import validate_scores
from conftest import DATA

def test_raster_lookup_reproduces_attached_scores(starter_rows):
    pytest.importorskip('rasterio')
    from floodcat.hazard.raster import RasterHazard
    assets, _ = validate_rows(starter_rows)
    with RasterHazard(DATA) as rasters:
        for asset in assets:
            scores = rasters.scores(asset)
            for t in TIERS:
                assert scores[t] == pytest.approx(asset.hazard[t], abs=1e-9)

def test_baseline_proxy_flags_12_of_24_hotspots():
    pytest.importorskip('rasterio')
    from floodcat.hazard.raster import RasterHazard
    with RasterHazard(DATA) as rasters:
        check = hotspot_check(load_hotspots(DATA/'nairobi_hotspots_geocoded.csv'), rasters)
    assert check['hotspot_count'] == 24
    assert check['flagged_any_tier'] == 12

def test_starter_scores_never_fall_as_tiers_get_rarer(starter_rows):
    assets, _ = validate_rows(starter_rows)
    for asset in assets:
        validate_scores(asset.hazard)

def test_nearest_hotspot_and_radius(config):
    hotspots = load_hotspots(DATA/'nairobi_hotspots_geocoded.csv')
    at_kibera = nearest_hotspot(-1.3113332, 36.7890001, hotspots, config)
    assert at_kibera['nearest_hotspot'] == 'Kibera' and at_kibera['hotspot_distance_m'] == 0
    assert hotspot_area(at_kibera) == 'Kibera'
    far = nearest_hotspot(-1.40, 36.62, hotspots, config)
    assert not far['within_hotspot_radius']
    assert hotspot_area(far) == 'no named hotspot within radius'

def test_missing_hazard_is_an_error_not_zero():
    with pytest.raises(ModelError):
        validate_scores({'extreme': 0.1, 'severe': None, 'moderate': .2, 'occasional': .3, 'common': .4})

def test_data_audit_runs_on_starter_kit():
    pytest.importorskip('rasterio')
    from floodcat.services.data_audit import audit_data
    audit = audit_data(DATA)
    assert audit['validation_error_count'] == 0 and audit['prepared_score_mismatches'] == 0
    assert audit['baseline_common_hotspots_positive'] == 12
