from .models import Exposure
from ..core.constants import CLASSES, TIERS, FEATURES
from ..core.numeric import bounded, finite, money
from ..core.errors import ModelError

def parse_bool(value):
    if isinstance(value,bool): return value
    if str(value).lower() in ("true","1"): return True
    if str(value).lower() in ("false","0"): return False
    raise ModelError("invalid_synthetic", "synthetic must explicitly be true or false")

def parse_row(row):
    required=("loc_id","lat","lon","housing_class","tiv_kes","synthetic","source")
    missing=[key for key in required if row.get(key) in (None,"")]
    if missing: raise ModelError("missing_fields", "Missing: "+", ".join(missing))
    identifier=str(row['loc_id']).strip()
    if not identifier: raise ModelError("invalid_id", "loc_id cannot be blank")
    c=str(row['housing_class']).strip()
    if c not in CLASSES: raise ModelError("unknown_construction", f"Unsupported class {c}")
    area=finite(row['floor_area_m2'],'floor_area_m2') if row.get('floor_area_m2') not in (None,'') else None
    cost=finite(row['cost_per_m2_kes'],'cost_per_m2_kes') if row.get('cost_per_m2_kes') not in (None,'') else None
    if any(x is not None and x<=0 for x in (area,cost)):
        raise ModelError("invalid_replacement_cost", "Area and cost/m² must be positive")
    hazard={t:bounded(row['hazard_score_'+t],t) for t in TIERS if row.get('hazard_score_'+t) not in (None,'')}
    features={f:bounded(row[f],f) for f in FEATURES[1:] if row.get(f) not in (None,'')}
    return Exposure(identifier,bounded(row['lat'],'lat',-90,90),bounded(row['lon'],'lon',-180,180),c,
                    money(row['tiv_kes']),parse_bool(row['synthetic']),str(row['source']),area,cost,hazard,features)

def validate_rows(rows):
    if not rows: raise ModelError("empty_portfolio", "Portfolio contains no records")
    accepted=[]; issues=[]; ids=set(); locations={}
    for index,row in enumerate(rows,1):
        try:
            asset=parse_row(row)
            if asset.loc_id in ids: raise ModelError("duplicate_id", "Duplicate loc_id; record excluded")
            ids.add(asset.loc_id)
            if not asset.synthetic: raise ModelError("real_portfolio_out_of_scope", "Hackathon accepts synthetic exposure only")
            accepted.append(asset)
            key=(asset.lat,asset.lon)
            if key in locations:
                issues.append(dict(row=index,loc_id=asset.loc_id,code="shared_coordinates",severity="warning",message="Same coordinates as "+locations[key]+"; retained because co-location is not proof of duplication"))
            locations[key]=asset.loc_id
            if asset.tiv_kes==0:
                issues.append(dict(row=index,loc_id=asset.loc_id,code="zero_tiv",severity="warning",message="Zero insured value"))
            if asset.floor_area_m2 and asset.cost_per_m2_kes:
                expected=asset.floor_area_m2*asset.cost_per_m2_kes
                if abs(float(asset.tiv_kes)-expected)>max(5000.,.1*expected):
                    issues.append(dict(row=index,loc_id=asset.loc_id,code="tiv_mismatch",severity="warning",message="TIV differs from area × cost/m²; supplied TIV retained"))
        except ModelError as exc:
            issues.append(dict(row=index,loc_id=str(row.get('loc_id','')),code=exc.code,severity="error",message=str(exc)))
    return accepted,issues
