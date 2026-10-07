"""Reviewed flood evidence: the only route by which AI output can change hazard."""
from dataclasses import dataclass, asdict
from datetime import date
from ..core.constants import MECHANISMS
from ..core.errors import ModelError
from ..core.geo import distance_m, in_coverage
from ..core.numeric import bounded

LOCATION_METHODS = ('nominatim', 'ai_estimate', 'manual')

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    quote: str
    event_date: str
    location_name: str
    lat: float
    lon: float
    location_method: str
    mechanism: str
    confidence: float
    independent_of_hotspot_list: bool
    approved: bool = False
    reviewer: str | None = None
    def __post_init__(self):
        for key in ('evidence_id','source','quote','location_name'):
            if not str(getattr(self,key)).strip(): raise ModelError('invalid_evidence',f'{key} required')
        if self.event_date:
            try: date.fromisoformat(self.event_date)
            except (TypeError,ValueError): raise ModelError('invalid_evidence','event_date must be ISO (YYYY-MM-DD) or blank') from None
        bounded(self.lat,'lat',-90,90);bounded(self.lon,'lon',-180,180);bounded(self.confidence,'confidence')
        if not in_coverage(self.lon,self.lat): raise ModelError('invalid_evidence',f'{self.location_name} is outside the Nairobi hazard maps')
        if self.mechanism not in MECHANISMS: raise ModelError('invalid_evidence',f'Unknown mechanism {self.mechanism}')
        if self.location_method not in LOCATION_METHODS: raise ModelError('invalid_evidence','Unknown location method')
        if self.approved and (not isinstance(self.reviewer,str) or not self.reviewer.strip()):
            raise ModelError('unreviewed_evidence','Approval requires named reviewer')
    def to_dict(self): return asdict(self)

def usable(evidence, config):
    """Approved, confident enough, and of a mechanism the proxy cannot see."""
    return [e for e in evidence if e.approved and e.confidence>=config.evidence_min_confidence and e.mechanism in config.evidence_mechanisms]

def evidence_signal(lat, lon, evidence, config):
    # Max, not sum: syndicated copies of one report must not stack.
    return max((e.confidence*(1-distance_m(lat,lon,e.lat,e.lon)/config.evidence_radius_m)
                for e in evidence if distance_m(lat,lon,e.lat,e.lon)<config.evidence_radius_m),default=0.)
