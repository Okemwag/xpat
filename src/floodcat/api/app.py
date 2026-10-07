import os
import secrets
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from ..core.config import ModelConfig
from ..core.errors import ModelError
from ..core.constants import TIERS
from ..storage.repository import Repository
from ..services.analysis import analyse
from ..ai.model import HotspotModel
from ..ai.evidence import Evidence
from ..ai.extraction import HttpEvidenceExtractor
from ..reporting.export import json_report, property_csv
from ..vulnerability.functions import matrix
from .schemas import AnalysisRequest, EvidenceRequest, ApprovalRequest, ExtractionRequest, CSVAnalysisRequest

def create_app(db_path=None,api_token=None,model_path=None):
    token=api_token if api_token is not None else os.getenv('FLOODCAT_API_TOKEN','')
    if os.getenv('FLOODCAT_ENV','development')=='production' and not token:
        raise RuntimeError('Production requires FLOODCAT_API_TOKEN')
    repo=Repository(db_path or os.getenv('FLOODCAT_DB','runtime/floodcat.sqlite3'))
    artifact=model_path or os.getenv('FLOODCAT_MODEL')
    model=HotspotModel.load(artifact) if artifact else None
    app=FastAPI(title='Nairobi Flood CAT API',version='0.1.0',description='Synthetic portfolio analysis; uncalibrated prototype')
    origins=[x.strip() for x in os.getenv('FLOODCAT_CORS_ORIGINS','http://localhost:3000').split(',') if x.strip()]
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST'],allow_headers=['Content-Type','X-API-Key'])
    def authenticate(x_api_key: Annotated[str | None,Header()]=None):
        if token and (not x_api_key or not secrets.compare_digest(x_api_key,token)):
            raise HTTPException(401,'Valid X-API-Key required')
    @app.exception_handler(ModelError)
    async def model_error(request,exc):
        return JSONResponse(status_code=404 if exc.code=='not_found' else 422,content={'code':exc.code,'message':str(exc)})
    @app.get('/health')
    def health(): return {'status':'ok','model_available':model is not None}
    @app.get('/v1/model',dependencies=[Depends(authenticate)])
    def metadata():
        config=ModelConfig()
        return {'config':config.to_dict(),'vulnerability_matrix':matrix(config),'ai_available':model is not None}
    @app.post('/v1/analyses',status_code=201,dependencies=[Depends(authenticate)])
    def new_analysis(request:AnalysisRequest):
        if request.enhanced and model is None: raise ModelError('model_unavailable','Train and configure FLOODCAT_MODEL before requesting enhancement')
        try: config=ModelConfig(**request.config) if request.config else ModelConfig()
        except TypeError: raise ModelError('invalid_config','Unknown or malformed configuration fields') from None
        result=analyse(request.rows,config,model=model if request.enhanced else None,evidence=repo.list_evidence(),allow_partial=request.allow_partial)
        repo.save_analysis(result)
        return result
    @app.post('/v1/analyses/csv',status_code=201,dependencies=[Depends(authenticate)])
    def csv_analysis(request:CSVAnalysisRequest):
        from ..exposure.loaders import parse_csv_text
        return new_analysis(AnalysisRequest(rows=parse_csv_text(request.csv_text),allow_partial=request.allow_partial,
                                            enhanced=request.enhanced,config=request.config))
    @app.get('/v1/analyses',dependencies=[Depends(authenticate)])
    def list_analyses(): return repo.list_analyses()
    @app.get('/v1/analyses/{identifier}',dependencies=[Depends(authenticate)])
    def get_analysis(identifier:str): return repo.get_analysis(identifier)
    @app.get('/v1/analyses/{identifier}/export',dependencies=[Depends(authenticate)])
    def export(identifier:str,format:str='json',run:str='baseline',tier:str='common'):
        result=repo.get_analysis(identifier)
        if format=='json': return Response(json_report(result),media_type='application/json',headers={'Content-Disposition':'attachment; filename="risk-report.json"'})
        if format!='csv' or run not in result['runs'] or tier not in TIERS:
            raise ModelError('invalid_export','Use json or csv with an available run and valid tier')
        return Response(property_csv(result,run,tier),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="property-losses.csv"'})
    @app.post('/v1/evidence',status_code=201,dependencies=[Depends(authenticate)])
    def add_evidence(request:EvidenceRequest):
        item=Evidence(**request.model_dump());repo.add_evidence(item);return item.to_dict()
    @app.get('/v1/evidence',dependencies=[Depends(authenticate)])
    def list_evidence(): return [e.to_dict() for e in repo.list_evidence()]
    @app.post('/v1/evidence/{identifier}/approve',dependencies=[Depends(authenticate)])
    def approve(identifier:str,request:ApprovalRequest): return repo.approve_evidence(identifier,request.reviewer).to_dict()
    @app.post('/v1/evidence/extract',dependencies=[Depends(authenticate)])
    def extract(request:ExtractionRequest):
        endpoint=os.getenv('FLOODCAT_EVIDENCE_ENDPOINT')
        if not endpoint: raise ModelError('provider_unavailable','Configure a project-contract evidence extraction provider')
        return {'candidates':HttpEvidenceExtractor(endpoint,os.getenv('FLOODCAT_EVIDENCE_TOKEN','')).extract(request.text,request.source)}
    return app
