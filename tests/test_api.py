import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from floodcat.api.app import create_app

@pytest.fixture
def db_url():
    value=os.getenv('TEST_DATABASE_URL')
    if not value:
        pytest.skip('PostGIS integration requires TEST_DATABASE_URL')
    return value

def test_api_roundtrip_auth_and_export(db_url,rows):
    client=TestClient(create_app(db_url,api_token='test-token'))
    assert client.get('/health').status_code==200
    assert client.post('/v1/analyses',json={'rows':rows}).status_code==401
    headers={'X-API-Key':'test-token'}
    response=client.post('/v1/analyses',json={'rows':rows},headers=headers)
    assert response.status_code==201,response.text
    report=response.json(); identifier=report['analysis_id']
    assert client.get('/v1/analyses/'+identifier,headers=headers).json()==report
    assert client.get('/v1/analyses',headers=headers).json()[0]['analysis_id']==identifier
    csv=client.get('/v1/analyses/'+identifier+'/export?format=csv',headers=headers)
    assert csv.status_code==200 and 'damage_ratio' in csv.text
    assert client.get('/v1/analyses/no-such-id',headers=headers).status_code==404
    enhanced=client.post('/v1/analyses',json={'rows':rows,'enhanced':True},headers=headers)
    assert enhanced.status_code==422 and enhanced.json()['code']=='model_unavailable'

def test_evidence_review_workflow(db_url):
    client=TestClient(create_app(db_url))
    identifier=str(uuid4())
    payload=dict(evidence_id=identifier,source='county report',quote='flooding',event_date='2026-03-01',
                 location_name='place',lat=-1.28,lon=36.86,confidence=.8,drainage_signal=.7)
    assert client.post('/v1/evidence',json=payload).status_code==201
    assert any(item['evidence_id']==identifier and not item['approved'] for item in client.get('/v1/evidence').json())
    assert client.post('/v1/evidence',json=payload).status_code==422
    assert client.post('/v1/evidence/'+identifier+'/approve',json={'reviewer':'Analyst'}).json()['approved']
    assert client.post('/v1/evidence/extract',json={'text':'flood report','source':'source'}).json()['code']=='provider_unavailable'

def test_production_requires_token(db_url,monkeypatch):
    monkeypatch.setenv('FLOODCAT_ENV','production')
    with pytest.raises(RuntimeError): create_app(db_url,api_token='')

def test_csv_ingestion_and_malformed_config(db_url,rows):
    import csv,io
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    client=TestClient(create_app(db_url))
    response=client.post('/v1/analyses/csv',json={'csv_text':stream.getvalue()})
    assert response.status_code==201,response.text
    assert response.json()['modelled_count']==4
    invalid=client.post('/v1/analyses',json={'rows':rows,'config':{'curves':None}})
    assert invalid.status_code==422 and invalid.json()['code']=='invalid_config'
