from pathlib import Path
import pytest
from floodcat.core.config import load_config
from floodcat.exposure.loaders import read_csv

DATA = Path(__file__).resolve().parents[1]/'data'

@pytest.fixture
def config():
    return load_config()

@pytest.fixture(scope='session')
def starter_rows():
    return read_csv(DATA/'exposure_nairobi_with_hazard.csv')

def row(loc_id='T-1', housing_class='permanent_masonry', tiv='1000000', scores=(0.1, 0.2, 0.3, 0.4, 0.5), **extra):
    tiers = ('extreme', 'severe', 'moderate', 'occasional', 'common')
    base = {'loc_id': loc_id, 'lat': '-1.28', 'lon': '36.82', 'housing_class': housing_class, 'tiv_kes': tiv,
            'floor_area_m2': '', 'cost_per_m2_kes': '', 'synthetic': 'True', 'source': 'test fixture',
            **{f'hazard_score_{t}': str(s) for t, s in zip(tiers, scores)}}
    return {**base, **extra}
