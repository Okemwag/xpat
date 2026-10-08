"""Evidence for what the AI hazard adjustment changed. Never reported as accuracy."""

from ..core.constants import TIERS
from ..core.geo import distance_m
from ..hazard.hotspots import hotspot_check
from ..hazard.interpretation import enhance, validate_scores
from .evidence import evidence_signal, usable


class _Adjusted:
    def __init__(self, provider, evidence, config):
        self.provider, self.evidence, self.config = provider, evidence, config

    def scores(self, asset):
        base = validate_scores(self.provider.scores(asset))
        return enhance(
            base,
            evidence_signal(asset.lat, asset.lon, self.evidence, self.config),
            self.config,
        )


def hotspot_comparison(hotspots, provider, evidence, config):
    """Hit rate on the 24 named hotspots before and after, using only evidence marked independent of
    the county hotspot list. Evidence drawn from that list would make the check circular."""
    applied = usable(evidence, config)
    independent = [e for e in applied if e.independent_of_hotspot_list]
    before = hotspot_check(hotspots, provider)
    after = hotspot_check(hotspots, _Adjusted(provider, independent, config))
    newly = [
        a["name"]
        for b, a in zip(before["points"], after["points"])
        if a["flagged_any_tier"] and not b["flagged_any_tier"]
    ]
    return {
        "evaluated_evidence_count": len(independent),
        "excluded_non_independent": len(applied) - len(independent),
        "before_flagged": before["flagged_any_tier"],
        "after_flagged": after["flagged_any_tier"],
        "hotspot_count": before["hotspot_count"],
        "newly_flagged": newly,
        "before_by_tier": before["flagged_by_tier"],
        "after_by_tier": after["flagged_by_tier"],
        "points": [
            {
                "name": b["name"],
                **{f"before_{t}": b[t] for t in TIERS},
                **{f"after_{t}": a[t] for t in TIERS},
                "before_flagged": b["flagged_any_tier"],
                "after_flagged": a["flagged_any_tier"],
            }
            for b, a in zip(before["points"], after["points"])
        ],
        "caveats": [
            "Positive-only check: the 24 places are known flood areas; there is no list of places known not to flood.",
            "Hotspot coordinates are approximate neighbourhood centres.",
            "Evidence near a hotspot will flag it by construction; the test is whether independent reports "
            "exist for the places the proxy misses, not whether the uplift formula works.",
        ],
    }


def spread(assets_scores, hotspots, config):
    """How far the uplift reaches: changed properties near and far from any named hotspot."""
    near = far = 0
    for asset, changed in assets_scores:
        if not changed:
            continue
        if (
            min(distance_m(asset.lat, asset.lon, h.lat, h.lon) for h in hotspots)
            <= config.hotspot_tag_radius_m
        ):
            near += 1
        else:
            far += 1
    return {"changed_near_hotspot": near, "changed_away_from_hotspots": far}


def describe_adjustment(ai):
    """Plain words for what produced the enhanced run: approved evidence, the drainage model, or both."""
    parts = []
    if ai.get("evidence_enabled", ai.get("enabled")) and ai.get(
        "applied_evidence_count"
    ):
        parts.append(
            f"{ai['applied_evidence_count']} reviewer-approved drainage report(s)"
        )
    if ai.get("drainage"):
        parts.append(
            f"the drainage model ({'learned' if ai['drainage']['mode'] == 'fitted' else 'prior'} weights)"
        )
    return (
        " and ".join(parts) or "the AI hazard adjustment (no approved evidence applied)"
    )
