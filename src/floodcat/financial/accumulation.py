from collections import defaultdict
from decimal import Decimal
from ..core.geo import grid_cell
from ..core.numeric import money_string
from ..hazard.hotspots import hotspot_area

def _pack(bucket,total):
    return [{'id':key,'property_count':v['property_count'],'tiv_kes':money_string(v['tiv']),'loss_kes':money_string(v['loss']),
             'loss_share_pct':float(v['loss']/total*100) if total else 0.}
            for key,v in sorted(bucket.items(),key=lambda pair:(-pair[1]['loss'],pair[0]))]

def group_losses(rows,config):
    keys={'geographic_grid':lambda r: grid_cell(r['lat'],r['lon'],config.grid_size_m),
          'construction':lambda r: r['housing_class']}
    if rows and 'nearest_hotspot' in rows[0]: keys['hotspot_area']=hotspot_area
    buckets={name:defaultdict(lambda: {'property_count':0,'tiv':Decimal(0),'loss':Decimal(0)}) for name in keys}
    total=Decimal(0)
    for row in rows:
        loss=Decimal(row['loss_kes']);total+=loss
        for name,key in keys.items():
            bucket=buckets[name][key(row)]
            bucket['property_count']+=1
            bucket['tiv']+=Decimal(row['tiv_kes'])
            bucket['loss']+=loss
    result={name:_pack(bucket,total) for name,bucket in buckets.items()}
    top=sorted(rows,key=lambda r:(-Decimal(r['loss_kes']),r['loc_id']))[:config.top_n]
    result['top_properties']=[{k:r[k] for k in ('loc_id','housing_class','tiv_kes','hazard_score','assumed_depth_m','damage_ratio','loss_kes',
                                                 'nearest_hotspot','hotspot_distance_m') if k in r} for r in top]
    result.update(grid_size_m=config.grid_size_m,hotspot_tag_radius_m=config.hotspot_tag_radius_m,
                  interpretation='Co-location concentration; cells and hotspot areas are not independent events or administrative zones')
    return result
