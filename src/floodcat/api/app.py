import os
import secrets
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from ..core.errors import ModelError, ReviewRequired
from ..core.constants import TIERS
from ..exposure.validation import summarise_issues
from ..services.runtime import Runtime
from ..ai.evidence import Evidence
from ..reporting.export import json_report, property_csv
from ..vulnerability.functions import matrix
from .schemas import AnalysisRequest, EvidenceRequest, ApprovalRequest, ExtractionRequest, CSVAnalysisRequest

def create_app(runtime=None,api_token=None):
    token=api_token if api_token is not None else os.getenv('FLOODCAT_API_TOKEN','')
    if os.getenv('FLOODCAT_ENV','development')=='production' and not token:
        raise RuntimeError('Production requires FLOODCAT_API_TOKEN')
    rt=runtime or Runtime()
    app=FastAPI(title='Nairobi Flood CAT API',version='0.3.0',description='Synthetic portfolio analysis; uncalibrated prototype')
    origins=[x.strip() for x in os.getenv('FLOODCAT_CORS_ORIGINS','http://localhost:3000').split(',') if x.strip()]
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST'],allow_headers=['Content-Type','X-API-Key'])
    def authenticate(x_api_key: Annotated[str | None,Header()]=None):
        if token and (not x_api_key or not secrets.compare_digest(x_api_key,token)):
            raise HTTPException(401,'Valid X-API-Key required')
    @app.exception_handler(ModelError)
    async def model_error(request,exc):
        body={'code':exc.code,'message':str(exc)}
        if isinstance(exc,ReviewRequired): body['issues']=summarise_issues(exc.issues)
        return JSONResponse(status_code=404 if exc.code=='not_found' else 422,content=body)
    @app.get('/health')
    def health():
        from ..ai.gemini import available
        return {'status':'ok','ai_available':available(),'store':type(rt.store).__name__}
    @app.get('/v1/model',dependencies=[Depends(authenticate)])
    def metadata(): return {'config':rt.config.to_dict(),'vulnerability_matrix':matrix(rt.config)}
    @app.post('/v1/analyses',status_code=201,dependencies=[Depends(authenticate)])
    def new_analysis(request:AnalysisRequest):
        config=rt.config.replace(**request.config) if request.config else None
        result=rt.run(request.rows,config=config,declare_synthetic=request.declare_synthetic,allow_partial=request.allow_partial,
                      ai_adjustment=request.ai_adjustment)
        rt.store.save_analysis(result)
        return result
    @app.post('/v1/analyses/csv',status_code=201,dependencies=[Depends(authenticate)])
    def csv_analysis(request:CSVAnalysisRequest):
        return new_analysis(AnalysisRequest(rows=rt.parse_upload(request.csv_text),allow_partial=request.allow_partial,
                                            declare_synthetic=request.declare_synthetic,ai_adjustment=request.ai_adjustment,config=request.config))
    @app.get('/v1/analyses',dependencies=[Depends(authenticate)])
    def list_analyses(): return rt.store.list_analyses()
    @app.get('/v1/analyses/{identifier}',dependencies=[Depends(authenticate)])
    def get_analysis(identifier:str): return rt.store.get_analysis(identifier)
    @app.get('/v1/analyses/{identifier}/export',dependencies=[Depends(authenticate)])
    def export(identifier:str,format:str='json',run:str='baseline',tier:str='common'):
        result=rt.store.get_analysis(identifier)
        if format=='json': return Response(json_report(result),media_type='application/json',headers={'Content-Disposition':'attachment; filename="risk-report.json"'})
        if format!='csv' or run not in result['runs'] or tier not in TIERS:
            raise ModelError('invalid_export','Use json or csv with an available run and valid tier')
        return Response(property_csv(result,run,tier),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="property-losses.csv"'})
    @app.post('/v1/evidence',status_code=201,dependencies=[Depends(authenticate)])
    def add_evidence(request:EvidenceRequest):
        item=Evidence(**request.model_dump());rt.store.add_evidence(item);return item.to_dict()
    @app.get('/v1/evidence',dependencies=[Depends(authenticate)])
    def list_evidence(): return [e.to_dict() for e in rt.store.list_evidence()]
    @app.post('/v1/evidence/{identifier}/approve',dependencies=[Depends(authenticate)])
    def approve(identifier:str,request:ApprovalRequest): return rt.store.approve_evidence(identifier,request.reviewer).to_dict()
    @app.post('/v1/evidence/extract',dependencies=[Depends(authenticate)])
    def extract(request:ExtractionRequest):
        from ..ai.extraction import extract as run_extraction
        return run_extraction(request.text,request.source,rt.llm(),rt.gazetteer())
    return app
