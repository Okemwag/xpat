from typing import Any
from pydantic import BaseModel, Field, ConfigDict

class AnalysisRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    rows: list[dict[str,Any]]=Field(min_length=1,max_length=10000)
    allow_partial: bool=False
    declare_synthetic: bool=False
    data_origin: str | None=Field(default=None,pattern='^(real|synthetic)$')
    visibility: str | None=Field(default=None,pattern='^(private|team|org)$')
    ai_adjustment: bool=False
    config: dict[str,Any] | None=None

class EvidenceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    evidence_id: str=Field(min_length=1,max_length=100)
    source: str=Field(min_length=1,max_length=2000)
    quote: str=Field(min_length=1,max_length=10000)
    event_date: str=''
    location_name: str=Field(min_length=1,max_length=200)
    lat: float=Field(ge=-90,le=90,allow_inf_nan=False)
    lon: float=Field(ge=-180,le=180,allow_inf_nan=False)
    location_method: str='manual'
    mechanism: str
    confidence: float=Field(ge=0,le=1,allow_inf_nan=False)
    independent_of_hotspot_list: bool

class ApprovalRequest(BaseModel):
    reviewer: str=Field(min_length=1,max_length=200)

class ExtractionRequest(BaseModel):
    text: str=Field(min_length=1,max_length=30000)
    source: str=Field(min_length=1,max_length=2000)

class CSVAnalysisRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    csv_text: str=Field(min_length=1,max_length=10_000_000)
    allow_partial: bool=False
    declare_synthetic: bool=False
    data_origin: str | None=Field(default=None,pattern='^(real|synthetic)$')
    visibility: str | None=Field(default=None,pattern='^(private|team|org)$')
    ai_adjustment: bool=False
    config: dict[str,Any] | None=None
