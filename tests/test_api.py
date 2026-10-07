import pytest
from conftest import DATA, row

pytest.importorskip('rasterio')
pytest.importorskip('httpx')

@pytest.fixture(scope='module')
def client(tmp_path_factory):
    from fastapi.testclient import TestClient
    from floodcat.api.app import create_app
    from floodcat.services.runtime import Runtime
    return TestClient(create_app(Runtime(data_dir=DATA, store_dir=tmp_path_factory.mktemp('api')), api_token=''))

def test_health_needs_no_database(client):
    assert client.get('/health').json()['store'] == 'LocalStore'

def test_csv_upload_without_scores_runs_and_is_saved(client):
    text = (DATA/'exposure_nairobi_synthetic.csv').read_text()
    response = client.post('/v1/analyses/csv', json={'csv_text': text})
    assert response.status_code == 201
    identifier = response.json()['analysis_id']
    assert client.get(f'/v1/analyses/{identifier}').json()['modelled_count'] == 600
    assert client.get(f'/v1/analyses/{identifier}/export?format=csv&tier=common').text.startswith('loc_id')

def test_review_required_returns_grouped_issues(client):
    response = client.post('/v1/analyses', json={'rows': [row(), row(loc_id='X', housing_class='castle')]})
    assert response.status_code == 422
    assert response.json()['issues'][0]['code'] == 'unknown_construction'

def test_unknown_analysis_is_404(client):
    assert client.get('/v1/analyses/../../etc').status_code == 404
