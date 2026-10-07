import hashlib
import json
from dataclasses import dataclass, field
from .constants import TIERS, CLASSES
from .errors import ModelError
from .numeric import bounded, finite

@dataclass(frozen=True)
class ModelConfig:
    version: str = "nairobi-prototype-v0.1"
    return_periods: dict = field(default_factory=lambda: dict(zip(TIERS, (10,25,50,100,250))))
    severity_knots: tuple = (0., .1, .3, .6, 1.)
    curves: dict = field(default_factory=lambda: {
        "informal_iron_sheet": (0., .15, .45, .75, .95),
        "semi_permanent": (0., .08, .30, .60, .90),
        "permanent_masonry": (0., .03, .18, .45, .85),
        "concrete_rcc": (0., .01, .10, .30, .80),
    })
    vulnerability_status: str = "illustrative_uncalibrated"
    vulnerability_source: str = "Team A build-guide qualitative shape; NOT digitized JRC parameters"
    vulnerability_mode: str = "score"
    max_depth_m: float = 4.
    enhancement_activation_threshold: float = .5
    uplift_weight: float = .25
    uplift_factors: dict = field(default_factory=lambda: dict(zip(TIERS, (.2,.4,.6,.8,1.))))
    grid_size_m: float = 1000.
    high_risk_threshold: float = .5
    evidence_radius_m: float = 1000.
    def __post_init__(self):
        try:
            self._validate()
            object.__setattr__(self, 'return_periods', {t:float(self.return_periods[t]) for t in TIERS})
            object.__setattr__(self, 'severity_knots', tuple(float(x) for x in self.severity_knots))
            object.__setattr__(self, 'curves', {c:tuple(float(x) for x in values) for c,values in self.curves.items()})
            object.__setattr__(self, 'uplift_factors', {t:float(self.uplift_factors[t]) for t in TIERS})
            for name in ('enhancement_activation_threshold','max_depth_m','uplift_weight','grid_size_m','high_risk_threshold','evidence_radius_m'):
                object.__setattr__(self,name,float(getattr(self,name)))
            for name in ('version','vulnerability_status','vulnerability_source'):
                if not isinstance(getattr(self,name),str) or not getattr(self,name).strip():
                    raise ModelError('invalid_config',f'{name} requires nonempty text')
        except ModelError:
            raise
        except (TypeError,ValueError,KeyError,AttributeError):
            raise ModelError('invalid_config','Malformed model configuration') from None
    def _validate(self):
        if set(self.return_periods) != set(TIERS):
            raise ModelError("invalid_config", "Exactly five return periods required")
        rps = [finite(self.return_periods[t], t) for t in TIERS]
        if any(x < 1 for x in rps) or any(a >= b for a,b in zip(rps,rps[1:])):
            raise ModelError("invalid_config", "Return periods must increase from extreme to common")
        knots = [finite(x, "knot") for x in self.severity_knots]
        if len(knots)<2 or knots[0]!=0 or knots[-1]!=1 or any(a>=b for a,b in zip(knots,knots[1:])):
            raise ModelError("invalid_config", "Score knots must strictly increase from 0 to 1")
        if set(self.curves)!=set(CLASSES):
            raise ModelError("invalid_config", "All four construction curves required")
        for c, values in self.curves.items():
            vals=[bounded(x,c,0,.95) for x in values]
            if len(vals)!=len(knots) or vals[0]!=0 or any(a>b for a,b in zip(vals,vals[1:])):
                raise ModelError("invalid_config", f"Invalid damage curve: {c}")
        if self.vulnerability_mode not in ("score","assumed_depth"):
            raise ModelError("invalid_config", "Unknown vulnerability mode")
        for name in ("max_depth_m","grid_size_m","evidence_radius_m"):
            if finite(getattr(self,name),name)<=0:
                raise ModelError("invalid_config", f"{name} must be positive")
        bounded(self.enhancement_activation_threshold,"enhancement_activation_threshold",0,.99)
        bounded(self.uplift_weight,"uplift_weight")
        bounded(self.high_risk_threshold,"high_risk_threshold")
        if set(self.uplift_factors)!=set(TIERS):
            raise ModelError("invalid_config", "All uplift factors required")
        factors=[bounded(self.uplift_factors[t],t) for t in TIERS]
        if any(a>b for a,b in zip(factors,factors[1:])):
            raise ModelError("invalid_config", "Uplift factors must increase from extreme to common")
    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)
    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_dict(),sort_keys=True).encode()).hexdigest()

def load_config(path=None):
    if path is None:
        return ModelConfig()
    with open(path) as stream:
        return ModelConfig(**json.load(stream))
