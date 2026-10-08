"""Nairobi flood CAT backend."""
from decimal import Decimal
from ..core.numeric import money_string
from ..vulnerability.functions import assumed_depth, damage_ratio
from .policy import insured_loss

def exposed_fraction(asset,config):
    """Share of insured value a ground-level flood can reach (ASSUMPTION).

    JRC damage factors describe flooded storeys. For a building with known storey counts, only the
    basements and the lowest `flooded_storeys_above_ground` storeys are exposed:
        fraction = (flooded storeys + basements) / (storeys above ground + basements)
    Value is assumed spread evenly across storeys. Without storey counts the whole value is exposed.
    """
    se=config.storey_exposure
    if not se['enabled'] or not asset.floors_above_ground: return 1.0
    basements=asset.basement_levels or 0
    flooded=min(se['flooded_storeys_above_ground'],asset.floors_above_ground)
    return (flooded+basements)/(asset.floors_above_ground+basements)

def property_loss(asset,score,config,tag=None):
    ratio=damage_ratio(score,asset.housing_class,config)
    fraction=exposed_fraction(asset,config)
    row={'loc_id':asset.loc_id,'lat':asset.lat,'lon':asset.lon,'housing_class':asset.housing_class,
         'tiv_kes':money_string(asset.tiv_kes),'hazard_score':score,'assumed_depth_m':assumed_depth(score,config),
         'damage_ratio':ratio,'exposed_fraction':fraction,'loss_kes':money_string(asset.tiv_kes*Decimal(str(ratio))*Decimal(str(fraction))),
         'synthetic':asset.synthetic,'exposure_source':asset.source}
    if config.policy_terms['enabled']:
        gross=Decimal(row['loss_kes'])
        row['insured_loss_kes']=money_string(insured_loss(gross,asset,config))
    if tag: row.update(tag)
    return row

def total_loss(rows,key='loss_kes'):
    return sum((Decimal(row[key]) for row in rows),Decimal(0))
