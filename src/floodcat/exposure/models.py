from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class Exposure:
    loc_id: str
    lat: float
    lon: float
    housing_class: str
    tiv_kes: Decimal
    synthetic: bool
    source: str
    floor_area_m2: float | None
    cost_per_m2_kes: float | None
    hazard: dict
    features: dict
