from dataclasses import dataclass, asdict
from datetime import date
from ..core.numeric import bounded
from ..core.errors import ModelError
from ..core.geo import distance_m

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    quote: str
    event_date: str
    location_name: str
    lat: float
    lon: float
    confidence: float
    drainage_signal: float
    approved: bool = False
    reviewer: str | None = None
    def __post_init__(self):
        for key in ('evidence_id','source','quote','location_name'):
            if not str(getattr(self,key)).strip(): raise ModelError('invalid_evidence',f'{key} required')
        try: date.fromisoformat(self.event_date)
        except (TypeError,ValueError): raise ModelError('invalid_evidence','ISO event_date required') from None
        bounded(self.lat,'lat',-90,90);bounded(self.lon,'lon',-180,180)
        bounded(self.confidence,'confidence');bounded(self.drainage_signal,'drainage_signal')
        if self.approved and (not isinstance(self.reviewer,str) or not self.reviewer.strip()):
            raise ModelError('unreviewed_evidence','Approval requires named reviewer')
    def to_dict(self): return asdict(self)

def evidence_signal(asset,evidence,config):
    # Max avoids repeatedly counting syndicated or duplicated reports.
    return max((e.confidence*e.drainage_signal*(1-distance_m(asset.lat,asset.lon,e.lat,e.lon)/config.evidence_radius_m)
                for e in evidence if e.approved and distance_m(asset.lat,asset.lon,e.lat,e.lon)<config.evidence_radius_m),default=0.)
