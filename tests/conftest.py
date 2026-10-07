from pathlib import Path
import pytest
from floodcat.exposure.loaders import read_csv
@pytest.fixture
def rows():
    return read_csv(Path(__file__).parents[1]/'data/demo/exposure.csv')
