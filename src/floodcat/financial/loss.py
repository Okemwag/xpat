from decimal import Decimal
from ..core.numeric import money_string
from ..vulnerability.functions import damage_ratio

def property_loss(asset,score,config):
    ratio=damage_ratio(score,asset.housing_class,config)
    return {'loc_id':asset.loc_id,'lat':asset.lat,'lon':asset.lon,'housing_class':asset.housing_class,
            'tiv_kes':money_string(asset.tiv_kes),'hazard_score':score,
            'assumed_depth_m':score*config.max_depth_m if config.vulnerability_mode=='assumed_depth' else None,
            'damage_ratio':ratio,'loss_kes':money_string(asset.tiv_kes*Decimal(str(ratio))),
            'synthetic':asset.synthetic,'exposure_source':asset.source}

def total_loss(rows):
    return sum((Decimal(row['loss_kes']) for row in rows),Decimal(0))
