from collections import defaultdict
from decimal import Decimal
from ..core.geo import grid_cell
from ..core.numeric import money_string

def group_losses(rows,config):
    groups=defaultdict(lambda: {'property_count':0,'tiv':Decimal(0),'loss':Decimal(0)})
    classes=defaultdict(lambda: {'property_count':0,'tiv':Decimal(0),'loss':Decimal(0)})
    for row in rows:
        for bucket,key in ((groups,grid_cell(row['lat'],row['lon'],config.grid_size_m)),(classes,row['housing_class'])):
            bucket[key]['property_count']+=1
            bucket[key]['tiv']+=Decimal(row['tiv_kes'])
            bucket[key]['loss']+=Decimal(row['loss_kes'])
    def pack(bucket):
        return [{'id':key,'property_count':v['property_count'],'tiv_kes':money_string(v['tiv']),'loss_kes':money_string(v['loss'])} for key,v in sorted(bucket.items(),key=lambda pair:pair[1]['loss'],reverse=True)]
    return {'geographic_grid':pack(groups),'construction':pack(classes),'grid_size_m':config.grid_size_m,
            'interpretation':'Co-location concentration; cells are not independent events or administrative zones'}
