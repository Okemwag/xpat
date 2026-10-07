import hashlib
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from .constants import TIERS, CLASSES, MECHANISMS
from .errors import ModelError
from .numeric import bounded, finite

# configs/default.json is the single source of truth; ModelConfig carries no default values.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3]/'configs'/'default.json'
AAL_TAILS = ('hold_rarest',)

@dataclass(frozen=True)
class ModelConfig:
    version: str
    return_periods: dict
    max_depth_m: float
    depth_sensitivity_m: tuple
    jrc_depth_m: tuple
    jrc_damage_factor: tuple
    vulnerability_status: str
    vulnerability_source: str
    class_adjustments: dict
    matrix_scores: tuple
    aal_zero_loss_return_period: float
    aal_tail: str
    hotspot_tag_radius_m: float
    top_n: int
    uplift_weight: float
    uplift_factors: dict
    evidence_mechanisms: tuple
    evidence_min_confidence: float
    grid_size_m: float
    evidence_radius_m: float
    def __post_init__(self):
        try:
            self._validate()
            object.__setattr__(self, 'return_periods', {t:float(self.return_periods[t]) for t in TIERS})
            for name in ('depth_sensitivity_m','jrc_depth_m','jrc_damage_factor','matrix_scores'):
                object.__setattr__(self, name, tuple(float(x) for x in getattr(self,name)))
            object.__setattr__(self, 'class_adjustments', {c:{'jrc_depth_scale':float(self.class_adjustments[c]['jrc_depth_scale']),
                                                              'damage_cap':float(self.class_adjustments[c]['damage_cap'])} for c in CLASSES})
            object.__setattr__(self, 'uplift_factors', {t:float(self.uplift_factors[t]) for t in TIERS})
            object.__setattr__(self, 'evidence_mechanisms', tuple(self.evidence_mechanisms))
            for name in ('evidence_min_confidence','max_depth_m','uplift_weight','grid_size_m',
                         'evidence_radius_m','aal_zero_loss_return_period','hotspot_tag_radius_m'):
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
        depths=[finite(x,'jrc_depth_m') for x in self.jrc_depth_m]
        damage=[bounded(x,'jrc_damage_factor') for x in self.jrc_damage_factor]
        if len(depths)<2 or len(depths)!=len(damage) or depths[0]!=0 or any(a>=b for a,b in zip(depths,depths[1:])):
            raise ModelError("invalid_config", "JRC depths must strictly increase from 0 and pair with damage factors")
        if damage[0]!=0 or any(a>b for a,b in zip(damage,damage[1:])):
            raise ModelError("invalid_config", "JRC damage factors must start at 0 and never decrease")
        if set(self.class_adjustments)!=set(CLASSES):
            raise ModelError("invalid_config", "All four construction classes need adjustments")
        for c in CLASSES:
            if finite(self.class_adjustments[c]['jrc_depth_scale'],c+'.jrc_depth_scale')<=0:
                raise ModelError("invalid_config", f"{c} depth scale must be positive")
            # Problem statement: buildings rarely lose all value; caps of 80–95% of value.
            bounded(self.class_adjustments[c]['damage_cap'],c+'.damage_cap',.8,.95)
        scores=[bounded(x,'matrix_scores') for x in self.matrix_scores]
        if not scores or any(a>=b for a,b in zip(scores,scores[1:])):
            raise ModelError("invalid_config", "Matrix scores must strictly increase within 0–1")
        for name in ("max_depth_m","grid_size_m","evidence_radius_m","hotspot_tag_radius_m"):
            if finite(getattr(self,name),name)<=0:
                raise ModelError("invalid_config", f"{name} must be positive")
        if not self.depth_sensitivity_m or any(finite(x,'depth_sensitivity_m')<=0 for x in self.depth_sensitivity_m):
            raise ModelError("invalid_config", "Depth sensitivity cases must be positive")
        zero=finite(self.aal_zero_loss_return_period,'aal_zero_loss_return_period')
        if not 1<=zero<rps[0]:
            raise ModelError("invalid_config", "AAL zero-loss return period must be at least 1 and below the most frequent tier")
        if self.aal_tail not in AAL_TAILS:
            raise ModelError("invalid_config", "Unknown AAL tail method")
        if isinstance(self.top_n,bool) or not isinstance(self.top_n,int) or self.top_n<1:
            raise ModelError("invalid_config", "top_n must be a positive integer")
        bounded(self.uplift_weight,"uplift_weight")
        bounded(self.evidence_min_confidence,"evidence_min_confidence")
        if not self.evidence_mechanisms or not set(self.evidence_mechanisms)<=set(MECHANISMS):
            raise ModelError("invalid_config", "evidence_mechanisms must be a non-empty subset of "+", ".join(MECHANISMS))
        if set(self.uplift_factors)!=set(TIERS):
            raise ModelError("invalid_config", "All uplift factors required")
        factors=[bounded(self.uplift_factors[t],t) for t in TIERS]
        if any(a>b for a,b in zip(factors,factors[1:])):
            raise ModelError("invalid_config", "Uplift factors must increase from extreme to common")
    def to_dict(self):
        return asdict(self)
    def replace(self, **changes):
        return ModelConfig(**{**self.to_dict(), **changes})
    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_dict(),sort_keys=True).encode()).hexdigest()

def load_config(path=None):
    path=path or os.getenv('FLOODCAT_CONFIG') or DEFAULT_CONFIG_PATH
    with open(path) as stream:
        try: return ModelConfig(**json.load(stream))
        except TypeError: raise ModelError('invalid_config','Unknown or missing configuration fields') from None
