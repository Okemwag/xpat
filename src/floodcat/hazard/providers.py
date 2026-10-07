from typing import Protocol
from ..core.constants import TIERS
from ..core.geo import in_coverage

class HazardProvider(Protocol):
    def scores(self, asset) -> dict: ...

class AttachedHazard:
    """Prepared CSV scores, constrained to documented raster footprint."""
    def scores(self, asset):
        if not in_coverage(asset.lon,asset.lat): return {t:None for t in TIERS}
        return {t:asset.hazard.get(t) for t in TIERS}
