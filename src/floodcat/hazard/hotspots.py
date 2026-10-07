"""Government-named flood hotspots: validation and location tagging only, never exposure.

Names are REAL (county mapping, March 2026); coordinates are approximate neighbourhood
centroids geocoded with OSM Nominatim, not positions of flooded buildings.
"""
from dataclasses import dataclass
from types import SimpleNamespace
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.geo import distance_m
from ..core.numeric import bounded
from ..exposure.loaders import read_csv

@dataclass(frozen=True)
class Hotspot:
    name: str
    lat: float
    lon: float

def load_hotspots(path):
    hotspots=[]
    for index,row in enumerate(read_csv(path),1):
        name=str(row.get('name') or '').strip()
        if not name: raise ModelError('invalid_hotspot',f'Hotspot row {index} has no name')
        hotspots.append(Hotspot(name,bounded(row.get('lat'),'lat',-90,90),bounded(row.get('lon'),'lon',-180,180)))
    if not hotspots: raise ModelError('invalid_hotspot','Hotspot file is empty')
    return hotspots

def nearest_hotspot(lat, lon, hotspots, config):
    nearest=min(hotspots,key=lambda h: distance_m(lat,lon,h.lat,h.lon))
    distance=distance_m(lat,lon,nearest.lat,nearest.lon)
    return {'nearest_hotspot':nearest.name,'hotspot_distance_m':round(distance,1),
            'within_hotspot_radius':distance<=config.hotspot_tag_radius_m}

def hotspot_area(tag):
    """Accumulation key: the nearest hotspot only if it lies within the configured radius."""
    return tag['nearest_hotspot'] if tag['within_hotspot_radius'] else 'no named hotspot within radius'

def hotspot_check(hotspots, provider):
    """A hotspot counts as flagged in a tier when its proxy score there is above zero."""
    points=[]
    for h in hotspots:
        scores=provider.scores(SimpleNamespace(lat=h.lat,lon=h.lon,hazard={}))
        if any(scores[t] is None for t in TIERS):
            raise ModelError('hazard_unavailable',f'Hotspot {h.name} lies outside hazard coverage')
        points.append({'name':h.name,'lat':h.lat,'lon':h.lon,**{t:scores[t] for t in TIERS},
                       'flagged_any_tier':any(scores[t]>0 for t in TIERS)})
    return {'hotspot_count':len(points),
            'flagged_by_tier':{t:sum(p[t]>0 for p in points) for t in TIERS},
            'flagged_any_tier':sum(p['flagged_any_tier'] for p in points),
            'rule':'score > 0 at the geocoded point counts as flagged',
            'points':points}
