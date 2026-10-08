import hashlib
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from .constants import TIERS, CLASSES, MECHANISMS
from .errors import ModelError
from .numeric import bounded, finite
from ..hazard.imd import validate_settings as validate_imd

# configs/default.json is the single source of truth; ModelConfig carries no default values.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "default.json"
AAL_TAILS = ("hold_rarest",)


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
    storey_exposure: dict
    policy_terms: dict
    reinsurance: dict
    uncertainty: dict
    year_loss_table: dict
    uplift_weight: float
    uplift_factors: dict
    evidence_mechanisms: tuple
    evidence_min_confidence: float
    grid_size_m: float
    evidence_radius_m: float
    imd_index: dict
    drainage_reports: dict

    def __post_init__(self):
        try:
            self._validate()
            object.__setattr__(
                self,
                "return_periods",
                {t: float(self.return_periods[t]) for t in TIERS},
            )
            for name in (
                "depth_sensitivity_m",
                "jrc_depth_m",
                "jrc_damage_factor",
                "matrix_scores",
            ):
                object.__setattr__(
                    self, name, tuple(float(x) for x in getattr(self, name))
                )
            object.__setattr__(
                self,
                "class_adjustments",
                {
                    c: {
                        "jrc_depth_scale": float(
                            self.class_adjustments[c]["jrc_depth_scale"]
                        ),
                        "damage_cap": float(self.class_adjustments[c]["damage_cap"]),
                    }
                    for c in CLASSES
                },
            )
            object.__setattr__(
                self,
                "uplift_factors",
                {t: float(self.uplift_factors[t]) for t in TIERS},
            )
            object.__setattr__(
                self, "evidence_mechanisms", tuple(self.evidence_mechanisms)
            )
            object.__setattr__(self, "imd_index", validate_imd(self.imd_index))
            from ..financial.reinsurance import validate_settings as validate_reinsurance

            object.__setattr__(self, "reinsurance", validate_reinsurance(self.reinsurance))
            from ..ai.drainage import validate_settings as validate_drainage

            object.__setattr__(self, "drainage_reports", validate_drainage(self.drainage_reports))
            object.__setattr__(
                self,
                "storey_exposure",
                {
                    "enabled": bool(self.storey_exposure["enabled"]),
                    "flooded_storeys_above_ground": int(
                        self.storey_exposure["flooded_storeys_above_ground"]
                    ),
                },
            )
            object.__setattr__(
                self,
                "policy_terms",
                {
                    "enabled": bool(self.policy_terms["enabled"]),
                    "deductible_pct_of_tiv": float(
                        self.policy_terms["deductible_pct_of_tiv"]
                    ),
                    "limit_pct_of_tiv": float(self.policy_terms["limit_pct_of_tiv"]),
                },
            )
            u = self.uncertainty
            object.__setattr__(
                self,
                "uncertainty",
                {
                    "trials": int(u["trials"]),
                    "damage_sigma": float(u["damage_sigma"]),
                    "correlation": float(u["correlation"]),
                    "seed": int(u["seed"]),
                    "interval_pct": tuple(float(x) for x in u["interval_pct"]),
                },
            )
            y = self.year_loss_table
            object.__setattr__(
                self,
                "year_loss_table",
                {
                    "years": int(y["years"]),
                    "bootstrap": int(y["bootstrap"]),
                    "seed": int(y["seed"]),
                    "band_pct": tuple(float(x) for x in y["band_pct"]),
                },
            )
            for name in (
                "evidence_min_confidence",
                "max_depth_m",
                "uplift_weight",
                "grid_size_m",
                "evidence_radius_m",
                "aal_zero_loss_return_period",
                "hotspot_tag_radius_m",
            ):
                object.__setattr__(self, name, float(getattr(self, name)))
            for name in ("version", "vulnerability_status", "vulnerability_source"):
                if (
                    not isinstance(getattr(self, name), str)
                    or not getattr(self, name).strip()
                ):
                    raise ModelError("invalid_config", f"{name} requires nonempty text")
        except ModelError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError):
            raise ModelError(
                "invalid_config", "Malformed model configuration"
            ) from None

    def _validate(self):
        if set(self.return_periods) != set(TIERS):
            raise ModelError("invalid_config", "Exactly five return periods required")
        rps = [finite(self.return_periods[t], t) for t in TIERS]
        if any(x < 1 for x in rps) or any(a >= b for a, b in zip(rps, rps[1:])):
            raise ModelError(
                "invalid_config", "Return periods must increase from extreme to common"
            )
        depths = [finite(x, "jrc_depth_m") for x in self.jrc_depth_m]
        damage = [bounded(x, "jrc_damage_factor") for x in self.jrc_damage_factor]
        if (
            len(depths) < 2
            or len(depths) != len(damage)
            or depths[0] != 0
            or any(a >= b for a, b in zip(depths, depths[1:]))
        ):
            raise ModelError(
                "invalid_config",
                "JRC depths must strictly increase from 0 and pair with damage factors",
            )
        if damage[0] != 0 or any(a > b for a, b in zip(damage, damage[1:])):
            raise ModelError(
                "invalid_config",
                "JRC damage factors must start at 0 and never decrease",
            )
        if set(self.class_adjustments) != set(CLASSES):
            raise ModelError(
                "invalid_config", "All four construction classes need adjustments"
            )
        for c in CLASSES:
            if (
                finite(
                    self.class_adjustments[c]["jrc_depth_scale"], c + ".jrc_depth_scale"
                )
                <= 0
            ):
                raise ModelError("invalid_config", f"{c} depth scale must be positive")
            # Problem statement: buildings rarely lose all value; caps of 80–95% of value.
            bounded(
                self.class_adjustments[c]["damage_cap"], c + ".damage_cap", 0.8, 0.95
            )
        scores = [bounded(x, "matrix_scores") for x in self.matrix_scores]
        if not scores or any(a >= b for a, b in zip(scores, scores[1:])):
            raise ModelError(
                "invalid_config", "Matrix scores must strictly increase within 0–1"
            )
        for name in (
            "max_depth_m",
            "grid_size_m",
            "evidence_radius_m",
            "hotspot_tag_radius_m",
        ):
            if finite(getattr(self, name), name) <= 0:
                raise ModelError("invalid_config", f"{name} must be positive")
        if not self.depth_sensitivity_m or any(
            finite(x, "depth_sensitivity_m") <= 0 for x in self.depth_sensitivity_m
        ):
            raise ModelError(
                "invalid_config", "Depth sensitivity cases must be positive"
            )
        zero = finite(self.aal_zero_loss_return_period, "aal_zero_loss_return_period")
        if not 1 <= zero < rps[0]:
            raise ModelError(
                "invalid_config",
                "AAL zero-loss return period must be at least 1 and below the most frequent tier",
            )
        if self.aal_tail not in AAL_TAILS:
            raise ModelError("invalid_config", "Unknown AAL tail method")
        if (
            isinstance(self.top_n, bool)
            or not isinstance(self.top_n, int)
            or self.top_n < 1
        ):
            raise ModelError("invalid_config", "top_n must be a positive integer")
        bounded(self.uplift_weight, "uplift_weight")
        bounded(self.evidence_min_confidence, "evidence_min_confidence")
        se = self.storey_exposure
        if set(se) != {"enabled", "flooded_storeys_above_ground"} or not isinstance(
            se["enabled"], bool
        ):
            raise ModelError(
                "invalid_config",
                "storey_exposure needs enabled (true/false) and flooded_storeys_above_ground",
            )
        if (
            isinstance(se["flooded_storeys_above_ground"], bool)
            or not isinstance(se["flooded_storeys_above_ground"], int)
            or not 1 <= se["flooded_storeys_above_ground"] <= 5
        ):
            raise ModelError(
                "invalid_config",
                "flooded_storeys_above_ground must be an integer from 1 to 5",
            )
        terms = self.policy_terms
        if set(terms) != {
            "enabled",
            "deductible_pct_of_tiv",
            "limit_pct_of_tiv",
        } or not isinstance(terms["enabled"], bool):
            raise ModelError(
                "invalid_config",
                "policy_terms needs enabled (true/false), deductible_pct_of_tiv and limit_pct_of_tiv",
            )
        deductible = bounded(terms["deductible_pct_of_tiv"], "deductible_pct_of_tiv")
        if not deductible < bounded(terms["limit_pct_of_tiv"], "limit_pct_of_tiv"):
            raise ModelError(
                "invalid_config", "Policy limit must exceed the deductible"
            )
        u = self.uncertainty
        if set(u) != {"trials", "damage_sigma", "correlation", "seed", "interval_pct"}:
            raise ModelError(
                "invalid_config",
                "uncertainty needs trials, damage_sigma, correlation, seed and interval_pct",
            )
        if (
            isinstance(u["trials"], bool)
            or not isinstance(u["trials"], int)
            or not 100 <= u["trials"] <= 20000
        ):
            raise ModelError(
                "invalid_config",
                "uncertainty.trials must be an integer between 100 and 20000",
            )
        bounded(u["damage_sigma"], "damage_sigma", 0, 2)
        bounded(u["correlation"], "correlation")
        if isinstance(u["seed"], bool) or not isinstance(u["seed"], int):
            raise ModelError("invalid_config", "uncertainty.seed must be an integer")
        low, high = (bounded(x, "interval_pct", 0, 100) for x in u["interval_pct"])
        y = self.year_loss_table
        if set(y) != {"years", "bootstrap", "seed", "band_pct"}:
            raise ModelError(
                "invalid_config",
                "year_loss_table needs years, bootstrap, seed and band_pct",
            )
        for key, lo, hi in (
            ("years", 1000, 200000),
            ("bootstrap", 20, 2000),
            ("seed", -(2**63), 2**63),
        ):
            if (
                isinstance(y[key], bool)
                or not isinstance(y[key], int)
                or not lo <= y[key] <= hi
            ):
                raise ModelError(
                    "invalid_config",
                    f"year_loss_table.{key} must be an integer between {lo} and {hi}",
                )
        b_low, b_high = (bounded(x, "band_pct", 0, 100) for x in y["band_pct"])
        if not b_low < b_high:
            raise ModelError(
                "invalid_config", "band_pct must be [low, high] percentiles"
            )
        if len(u["interval_pct"]) != 2 or not low < high:
            raise ModelError(
                "invalid_config", "interval_pct must be [low, high] percentiles"
            )
        if not self.evidence_mechanisms or not set(self.evidence_mechanisms) <= set(
            MECHANISMS
        ):
            raise ModelError(
                "invalid_config",
                "evidence_mechanisms must be a non-empty subset of "
                + ", ".join(MECHANISMS),
            )
        if set(self.uplift_factors) != set(TIERS):
            raise ModelError("invalid_config", "All uplift factors required")
        factors = [bounded(self.uplift_factors[t], t) for t in TIERS]
        if any(a > b for a, b in zip(factors, factors[1:])):
            raise ModelError(
                "invalid_config", "Uplift factors must increase from extreme to common"
            )

    def to_dict(self):
        return asdict(self)

    def replace(self, **changes):
        return ModelConfig(**{**self.to_dict(), **changes})

    @property
    def fingerprint(self):
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True).encode()
        ).hexdigest()


def upgrade(stored):
    """Bring an assumption set saved before a field existed up to date, with that feature switched off.

    Only fields added later are filled; anything else missing is still an error. A house view approved before the
    infrastructure-deficit index existed therefore keeps its original results.
    """
    stored = dict(stored)
    with open(DEFAULT_CONFIG_PATH) as stream:
        shipped = json.load(stream)
    if "imd_index" not in stored:
        stored["imd_index"] = {**shipped["imd_index"], "enabled": False}
    if "reinsurance" not in stored:
        stored["reinsurance"] = {**shipped["reinsurance"], "enabled": False}
    if "drainage_reports" not in stored:
        # Report scoring only proposes evidence; nothing changes hazard until a reviewer approves it.
        stored["drainage_reports"] = shipped["drainage_reports"]
    return stored


def load_config(path=None):
    path = path or os.getenv("FLOODCAT_CONFIG") or DEFAULT_CONFIG_PATH
    with open(path) as stream:
        try:
            return ModelConfig(**json.load(stream))
        except TypeError:
            raise ModelError(
                "invalid_config", "Unknown or missing configuration fields"
            ) from None
