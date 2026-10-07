from fastapi.testclient import TestClient
from floodcat.api.app import create_app

def test_api_roundtrip_auth_and_export(tmp_path,rows):
    client=TestClient(create_app(tmp_path/'db.sqlite',api_token='test-token'))
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

def test_evidence_review_workflow(tmp_path):
    client=TestClient(create_app(tmp_path/'db.sqlite'))
    payload=dict(evidence_id='e1',source='county report',quote='flooding',event_date='2026-03-01',
                 location_name='place',lat=-1.28,lon=36.86,confidence=.8,drainage_signal=.7)
    assert client.post('/v1/evidence',json=payload).status_code==201
    assert client.get('/v1/evidence').json()[0]['approved'] is False
    assert client.post('/v1/evidence',json=payload).status_code==422
    assert client.post('/v1/evidence/e1/approve',json={'reviewer':'Analyst'}).json()['approved']
    assert client.post('/v1/evidence/extract',json={'text':'flood report','source':'source'}).json()['code']=='provider_unavailable'

def test_production_requires_token(tmp_path,monkeypatch):
    import pytest
    monkeypatch.setenv('FLOODCAT_ENV','production')
    with pytest.raises(RuntimeError): create_app(tmp_path/'db.sqlite',api_token='')

def test_csv_ingestion_and_malformed_config(tmp_path,rows):
    import csv,io
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    client=TestClient(create_app(tmp_path/'db.sqlite'))
    response=client.post('/v1/analyses/csv',json={'csv_text':stream.getvalue()})
    assert response.status_code==201,response.text
    assert response.json()['modelled_count']==4
    invalid=client.post('/v1/analyses',json={'rows':rows,'config':{'curves':None}})
    assert invalid.status_code==422 and invalid.json()['code']=='invalid_config'
