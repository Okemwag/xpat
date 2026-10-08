"""Nairobi flood CAT backend."""
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import bounded

def validate_scores(scores):
    if any(scores.get(t) is None for t in TIERS):
        raise ModelError("hazard_unavailable", "No hazard value at this location (off the hazard maps or a masked cell)")
    values=[bounded(scores[t],t) for t in TIERS]
    if any(a>b+1e-9 for a,b in zip(values,values[1:])):
        raise ModelError("nonmonotonic_hazard", "Scores must not decrease from extreme to common; do not reorder losses to hide this")
    return dict(zip(TIERS,values))

def enhance(scores, signal, config, weight=None):
    """Raise scores toward 1 where approved drainage evidence or the drainage model applies (AI stage, ASSUMPTION mapping).

    s' = 1 - (1 - s)(1 - w·f_tier·signal). Both factors shrink as tiers get rarer, so the
    adjusted scores keep the extreme→common order. The evidence signal is not a depth or a
    probability; the weight and tier factors that turn it into severity are config assumptions.
    """
    signal=bounded(signal,'evidence_signal')
    weight=config.uplift_weight if weight is None else bounded(weight,'uplift_weight')
    if signal==0: return validate_scores(dict(scores))
    # max() guards against floating-point round-off pulling a score below its baseline.
    return validate_scores({t: max(scores[t],1-(1-scores[t])*(1-weight*config.uplift_factors[t]*signal)) for t in TIERS})
