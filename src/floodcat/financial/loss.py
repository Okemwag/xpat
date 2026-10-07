"""Nairobi flood CAT backend."""
from decimal import Decimal
from ..core.numeric import money_string
from ..vulnerability.functions import assumed_depth, damage_ratio
from .policy import insured_loss

def property_loss(asset,score,config,tag=None):
    ratio=damage_ratio(score,asset.housing_class,config)
    row={'loc_id':asset.loc_id,'lat':asset.lat,'lon':asset.lon,'housing_class':asset.housing_class,
         'tiv_kes':money_string(asset.tiv_kes),'hazard_score':score,'assumed_depth_m':assumed_depth(score,config),
         'damage_ratio':ratio,'loss_kes':money_string(asset.tiv_kes*Decimal(str(ratio))),
         'synthetic':asset.synthetic,'exposure_source':asset.source}
    if config.policy_terms['enabled']:
        gross=Decimal(row['loss_kes'])
        row['insured_loss_kes']=money_string(insured_loss(gross,asset,config))
    if tag: row.update(tag)
    return row

def total_loss(rows,key='loss_kes'):
    return sum((Decimal(row[key]) for row in rows),Decimal(0))
