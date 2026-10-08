import hashlib
import json
import os
import re
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
    drainage_model: dict
    evidence_harvest: dict
    satellite_check: dict
    building_attributes: dict
    quality_checks: dict
    public_notes: dict

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
            for name, section in _ai_sections(self).items():
                object.__setattr__(self, name, section)
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


DRAINAGE_FEATURES = ("low_terrain", "built_density", "drain_gap", "culvert_proximity")


def _int(value, name, low, high):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise ModelError(
            "invalid_config", f"{name} must be an integer between {low} and {high}"
        )
    return value


def _positive(value, name):
    if finite(value, name) <= 0:
        raise ModelError("invalid_config", f"{name} must be positive")
    return float(value)


def _keys(section, name, keys):
    if not isinstance(section, dict) or set(section) != set(keys):
        raise ModelError("invalid_config", f"{name} needs exactly: {', '.join(keys)}")


def _ai_sections(cfg):
    """Validate and normalise the settings of the AI enhancement features (all ASSUMPTIONS, documented in docs/AI_ENHANCEMENTS.md)."""
    d = cfg.drainage_model
    _keys(
        d,
        "drainage_model",
        (
            "weight",
            "probability_threshold",
            "prior_intercept",
            "prior_weights",
            "drain_reach_m",
            "culvert_reach_m",
            "density_radius_m",
            "density_saturation",
            "min_training_positives",
            "background_points",
            "background_exclusion_m",
            "l2",
            "seed",
        ),
    )
    _keys(d["prior_weights"], "drainage_model.prior_weights", DRAINAGE_FEATURES)
    drainage = {
        "weight": bounded(d["weight"], "drainage_model.weight"),
        "probability_threshold": bounded(
            d["probability_threshold"], "probability_threshold", 0, 0.99
        ),
        "prior_intercept": finite(d["prior_intercept"], "prior_intercept"),
        "prior_weights": {
            k: finite(d["prior_weights"][k], k) for k in DRAINAGE_FEATURES
        },
        **{
            k: _positive(d[k], k)
            for k in (
                "drain_reach_m",
                "culvert_reach_m",
                "density_radius_m",
                "background_exclusion_m",
            )
        },
        "density_saturation": _int(
            d["density_saturation"], "density_saturation", 1, 100000
        ),
        "min_training_positives": _int(
            d["min_training_positives"], "min_training_positives", 2, 10000
        ),
        "background_points": _int(
            d["background_points"], "background_points", 20, 100000
        ),
        "l2": bounded(d["l2"], "l2", 0, 1000),
        "seed": _int(d["seed"], "drainage_model.seed", -(2**63), 2**63),
    }
    h = cfg.evidence_harvest
    _keys(
        h,
        "evidence_harvest",
        ("queries", "timespan", "max_articles", "hotspot_list_threshold"),
    )
    queries = [str(q).strip() for q in h["queries"] if str(q).strip()]
    if not queries or any(len(q) > 200 for q in queries):
        raise ModelError(
            "invalid_config",
            "evidence_harvest.queries needs 1+ queries of at most 200 characters",
        )
    if not isinstance(h["timespan"], str) or not re.fullmatch(
        r"\d{1,3}(min|h|d|w|m|y)", h["timespan"]
    ):
        raise ModelError(
            "invalid_config", "evidence_harvest.timespan must look like 3m, 1y or 30d"
        )
    harvest = {
        "queries": tuple(queries),
        "timespan": h["timespan"],
        "max_articles": _int(h["max_articles"], "max_articles", 1, 50),
        "hotspot_list_threshold": _int(
            h["hotspot_list_threshold"], "hotspot_list_threshold", 2, 50
        ),
    }
    s = cfg.satellite_check
    _keys(s, "satellite_check", ("sample_points", "seed"))
    satellite = {
        "sample_points": _int(s["sample_points"], "sample_points", 20, 100000),
        "seed": _int(s["seed"], "satellite_check.seed", -(2**63), 2**63),
    }
    b = cfg.building_attributes
    _keys(
        b,
        "building_attributes",
        ("storey_height_m", "min_building_height_m", "search_radius_m", "max_floors"),
    )
    building = {
        k: _positive(b[k], k)
        for k in ("storey_height_m", "min_building_height_m", "search_radius_m")
    }
    building["max_floors"] = _int(b["max_floors"], "max_floors", 1, 200)
    q = cfg.quality_checks
    _keys(q, "quality_checks", ("cost_ratio_factor", "tiv_ratio_band", "units_factor"))
    band = tuple(_positive(x, "tiv_ratio_band") for x in q["tiv_ratio_band"])
    if len(band) != 2 or not band[0] < band[1]:
        raise ModelError(
            "invalid_config", "quality_checks.tiv_ratio_band must be [low, high]"
        )
    quality = {
        "cost_ratio_factor": _positive(q["cost_ratio_factor"], "cost_ratio_factor"),
        "tiv_ratio_band": band,
        "units_factor": _positive(q["units_factor"], "units_factor"),
    }
    if quality["cost_ratio_factor"] <= 1 or quality["units_factor"] <= 1:
        raise ModelError("invalid_config", "quality check factors must exceed 1")
    n = cfg.public_notes
    _keys(n, "public_notes", ("radius_m", "spacing_m"))
    notes = {k: _positive(n[k], k) for k in ("radius_m", "spacing_m")}
    if notes["radius_m"] / notes["spacing_m"] > 100:
        raise ModelError(
            "invalid_config", "public_notes.spacing_m is too fine for the radius"
        )
    return {
        "drainage_model": drainage,
        "evidence_harvest": harvest,
        "satellite_check": satellite,
        "building_attributes": building,
        "quality_checks": quality,
        "public_notes": notes,
    }


def merge_defaults(stored):
    """Fill settings added after an assumption set was saved from the shipped defaults (new sections only, never edits).

    A filled-in reinsurance section starts switched off, so a house view approved before reinsurance existed keeps
    the results it was approved on.
    """
    shipped = load_config(DEFAULT_CONFIG_PATH).to_dict()
    filled = {k: v for k, v in shipped.items() if k not in stored}
    if "reinsurance" in filled:
        filled["reinsurance"] = {**filled["reinsurance"], "enabled": False}
    return {**filled, **stored}


def load_config(path=None):
    path = path or os.getenv("FLOODCAT_CONFIG") or DEFAULT_CONFIG_PATH
    with open(path) as stream:
        try:
            return ModelConfig(**json.load(stream))
        except TypeError:
            raise ModelError(
                "invalid_config", "Unknown or missing configuration fields"
            ) from None
