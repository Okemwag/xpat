from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import bounded

def validate_scores(scores):
    if any(scores.get(t) is None for t in TIERS):
        raise ModelError("hazard_unavailable", "Missing score or property outside model coverage")
    values=[bounded(scores[t],t) for t in TIERS]
    if any(a>b+1e-9 for a,b in zip(values,values[1:])):
        raise ModelError("nonmonotonic_hazard", "Scores must not decrease from extreme to common; do not reorder losses to hide this")
    return dict(zip(TIERS,values))

def enhance(scores, probability, config):
    # Learned hotspot probability is NOT annual flood probability or physical intensity.
    # Its conversion to severity uplift is a separately disclosed assumption.
    probability=bounded(probability,'hotspot_probability')
    activation=max(0.,(probability-config.enhancement_activation_threshold)/(1-config.enhancement_activation_threshold))
    return validate_scores({t: min(1.,scores[t]+config.uplift_weight*config.uplift_factors[t]*activation*(1-scores[t])) for t in TIERS})
