"""Exposure contract. CSV uploads and AI-ingested rows pass through exactly this validation."""
import re
from decimal import Decimal
from statistics import median
from .models import Exposure
from ..core.constants import CLASSES, CLASS_ALIASES, TIERS
from ..core.geo import in_coverage
from ..core.numeric import bounded, finite, money
from ..core.errors import ModelError

REQUIRED = ("loc_id","lat","lon","housing_class","tiv_kes","synthetic","source")
MAX_TEXT = 500
OUTLIER_FACTOR = 100

def parse_bool(value):
    if isinstance(value,bool): return value
    text=str(value).strip().lower()
    if text in ("true","1","yes","y","t"): return True
    if text in ("false","0","no","n","f"): return False
    raise ModelError("invalid_synthetic", "synthetic must be true or false")

def parse_class(value):
    """Return (class, alias_used). Unknown spellings are errors, not guesses."""
    key=re.sub(r'[\s\-/]+','_',str(value).strip().lower()).strip('_')
    if key in CLASSES: return key,None
    if key in CLASS_ALIASES: return CLASS_ALIASES[key],str(value).strip()
    raise ModelError("unknown_construction", f"Unsupported housing_class '{value}'; use one of "+", ".join(CLASSES))

def parse_money(value, field="tiv_kes"):
    """Accepts 1,250,000 / KES 1.25m / 300k / 2bn; rejects anything else."""
    text=re.sub(r'^(kes|ksh|kshs)\.?','',str(value).strip().lower()).strip()
    text=re.sub(r'[,\s_]','',text)
    match=re.fullmatch(r'([0-9]*\.?[0-9]+(?:e[+-]?[0-9]+)?)(k|m|mn|bn|b)?',text)
    if not match: raise ModelError("invalid_money", f"{field} '{value}' is not a number")
    scale={None:1,'k':10**3,'m':10**6,'mn':10**6,'b':10**9,'bn':10**9}[match.group(2)]
    return money(Decimal(match.group(1))*scale,field)

def parse_coordinates(row):
    lat=finite(row['lat'],'lat'); lon=finite(row['lon'],'lon')
    if lat==0 and lon==0: raise ModelError("missing_coordinates", "lat/lon are 0,0 — the location is missing")
    if in_coverage(lat,lon) and not in_coverage(lon,lat):
        raise ModelError("swapped_coordinates", "lat and lon appear swapped (Nairobi is about lat -1.3, lon 36.8)")
    bounded(lat,'lat',-90,90); bounded(lon,'lon',-180,180)
    if not in_coverage(lon,lat):
        raise ModelError("outside_coverage", f"({lat:.4f}, {lon:.4f}) is outside the Nairobi hazard maps; no hazard can be assigned")
    return lat,lon

def text_field(row,key):
    value=str(row[key]).strip()
    if not value: raise ModelError("missing_fields", f"{key} is blank")
    if len(value)>MAX_TEXT: raise ModelError("text_too_long", f"{key} exceeds {MAX_TEXT} characters")
    return value

def optional_positive(row,key):
    if row.get(key) in (None,''): return None
    value=finite(str(row[key]).replace(',',''),key)
    if value<=0: raise ModelError("invalid_replacement_cost", f"{key} must be positive")
    return value

def parse_row(row):
    missing=[key for key in REQUIRED if row.get(key) in (None,"")]
    if missing: raise ModelError("missing_fields", "Missing: "+", ".join(missing))
    notes=[]
    identifier=text_field(row,'loc_id')
    c,alias=parse_class(row['housing_class'])
    if alias: notes.append(("class_alias",f"housing_class '{alias}' read as {c}"))
    lat,lon=parse_coordinates(row)
    area=optional_positive(row,'floor_area_m2'); cost=optional_positive(row,'cost_per_m2_kes')
    supplied=[t for t in TIERS if row.get('hazard_score_'+t) not in (None,'')]
    hazard={t:bounded(row['hazard_score_'+t],'hazard_score_'+t) for t in supplied}
    if supplied and len(supplied)<len(TIERS):
        notes.append(("partial_hazard_scores","Only some hazard_score columns supplied; scores will come from the hazard maps"))
    asset=Exposure(identifier,lat,lon,c,parse_money(row['tiv_kes']),parse_bool(row['synthetic']),text_field(row,'source'),area,cost,hazard)
    return asset,notes

def check_columns(rows):
    present=set().union(*(r.keys() for r in rows)) if rows else set()
    missing=[k for k in REQUIRED if k not in present]
    if missing:
        hint=" Tick 'declare synthetic' to supply synthetic/source." if set(missing)<={'synthetic','source'} else ""
        raise ModelError("missing_columns", "Required columns missing: "+", ".join(missing)+"."+hint)

def apply_declarations(rows, declare_synthetic=False, source_label=None, assign_missing_ids=False):
    """Explicit, user-confirmed fills for upload convenience. Never applied implicitly."""
    prepared=[]; notes=[]
    for index,row in enumerate(rows,1):
        row=dict(row)
        if declare_synthetic and row.get('synthetic') in (None,''):
            row['synthetic']='True'; row['source']=row.get('source') or (source_label or 'uploaded; declared synthetic by user')
        if assign_missing_ids and row.get('loc_id') in (None,''):
            row['loc_id']=f'UPL-{index:05d}'
        prepared.append(row)
    if declare_synthetic: notes.append('synthetic/source filled from user declaration where blank')
    if assign_missing_ids: notes.append('blank loc_id replaced with UPL-<row number>')
    return prepared,notes

def validate_rows(rows):
    if not rows: raise ModelError("empty_portfolio", "Portfolio contains no records")
    check_columns(rows)
    accepted=[]; issues=[]; ids=set(); locations={}
    for index,row in enumerate(rows,1):
        try:
            asset,notes=parse_row(row)
            if asset.loc_id in ids: raise ModelError("duplicate_id", f"Duplicate loc_id {asset.loc_id}; later record excluded")
            if not asset.synthetic: raise ModelError("real_portfolio_out_of_scope", "Hackathon accepts synthetic exposure only")
            ids.add(asset.loc_id)
            accepted.append(asset)
            for code,message in notes:
                issues.append(dict(row=index,loc_id=asset.loc_id,code=code,severity="warning",message=message))
            key=(asset.lat,asset.lon)
            if key in locations:
                issues.append(dict(row=index,loc_id=asset.loc_id,code="shared_coordinates",severity="warning",message="Same coordinates as "+locations[key]+"; retained because co-location is not proof of duplication"))
            locations.setdefault(key,asset.loc_id)
            if asset.tiv_kes==0:
                issues.append(dict(row=index,loc_id=asset.loc_id,code="zero_tiv",severity="warning",message="Zero insured value"))
            if asset.floor_area_m2 and asset.cost_per_m2_kes:
                expected=asset.floor_area_m2*asset.cost_per_m2_kes
                if abs(float(asset.tiv_kes)-expected)>max(5000.,.1*expected):
                    issues.append(dict(row=index,loc_id=asset.loc_id,code="tiv_mismatch",severity="warning",message="TIV differs from area × cost/m²; supplied TIV retained"))
        except ModelError as exc:
            issues.append(dict(row=index,loc_id=str(row.get('loc_id','')),code=exc.code,severity="error",message=str(exc)))
    positive=[a.tiv_kes for a in accepted if a.tiv_kes>0]
    if len(positive)>=10:
        mid=median(positive)
        for a in accepted:
            if a.tiv_kes>OUTLIER_FACTOR*mid:
                issues.append(dict(row=None,loc_id=a.loc_id,code="tiv_outlier",severity="warning",message=f"TIV is over {OUTLIER_FACTOR}× the portfolio median; check units"))
    return accepted,issues

def summarise_issues(issues):
    """Group issues by code so 600 identical warnings read as one line."""
    groups={}
    for i in issues:
        g=groups.setdefault((i['severity'],i['code']),{'severity':i['severity'],'code':i['code'],'count':0,'example':i['message'],'loc_ids':[]})
        g['count']+=1
        if len(g['loc_ids'])<10: g['loc_ids'].append(i['loc_id'])
    return sorted(groups.values(),key=lambda g:(g['severity']!='error',-g['count']))
