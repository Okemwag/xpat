import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from ..core.config import load_config
from ..core.constants import TIERS
from ..core.errors import ModelError, ReviewRequired
from ..core.numeric import money_string
from ..exposure.validation import validate_rows
from ..hazard.providers import AttachedHazard
from ..hazard.interpretation import validate_scores, enhance
from ..hazard.hotspots import nearest_hotspot
from ..hazard.imd import index_value, uplift
from ..ai.evidence import evidence_signal, usable
from ..ai.evaluation import spread
from ..financial.loss import property_loss, total_loss
from ..financial.ep import ep_curve, average_annual_loss
from ..financial.accumulation import group_losses
from ..financial.reinsurance import programme as reinsurance_programme
from ..reporting.provenance import provenance, exposure_origin

SUPPLIED_SCORE_TOLERANCE = 1e-6


def property_aal(scenarios, config):
    """Each property's own average annual loss (same integration as the portfolio), largest first.

    The integral is linear in the losses, so these add up to the portfolio AAL (to rounding).
    """
    by_id = {}
    for tier, rows in scenarios.items():
        for r in rows:
            e = by_id.setdefault(r["loc_id"], {"gross": {}, "insured": {}, "housing_class": r["housing_class"],
                                               "tiv_kes": r["tiv_kes"]})
            e["gross"][tier] = Decimal(r["loss_kes"])
            if "insured_loss_kes" in r:
                e["insured"][tier] = Decimal(r["insured_loss_kes"])
    out = []
    for loc_id, e in by_id.items():
        if not any(e["gross"].values()):
            continue
        row = {"loc_id": loc_id, "housing_class": e["housing_class"], "tiv_kes": e["tiv_kes"],
               "aal_kes": average_annual_loss(e["gross"], config)["aal_kes"]}
        if e["insured"]:
            row["insured_aal_kes"] = average_annual_loss(e["insured"], config)["aal_kes"]
        out.append(row)
    return sorted(out, key=lambda r: (-Decimal(r["aal_kes"]), r["loc_id"]))


def analyse(
    rows,
    config=None,
    provider=None,
    evidence=(),
    allow_partial=False,
    hotspots=(),
    ai_adjustment=False,
    synthetic_only=False,
    imd=None,
):
    """Run the full chain for one portfolio. Pure: no files, network or database.

    `imd` is the infrastructure-deficit grid (hazard/imd.ImdGrid); it is applied to the hazard scores of every run
    when config.imd_index is enabled, before any AI evidence.
    """
    config = config or load_config()
    imd_on = config.imd_index["enabled"]
    if imd_on and imd is None:
        raise ModelError(
            "missing_imd_grid",
            "The infrastructure-deficit index is switched on but its grid is not loaded",
        )
    provider = provider or AttachedHazard()
    hotspots = tuple(hotspots)
    evidence = tuple(evidence)
    applied = usable(evidence, config) if ai_adjustment else []
    assets, issues = validate_rows(rows, synthetic_only)
    results = {"baseline": {t: [] for t in TIERS}}
    if ai_adjustment:
        results["enhanced"] = {t: [] for t in TIERS}
    excluded = []
    hazard_ok = []
    changes = []
    signals = {}
    imd_changes = {}
    terrain_only = {t: Decimal(0) for t in TIERS}
    for asset in assets:
        try:
            scores = provider.scores(asset)
            baseline = validate_scores(scores)
            if not isinstance(provider, AttachedHazard) and len(asset.hazard) == len(
                TIERS
            ):
                diff = max(abs(asset.hazard[t] - baseline[t]) for t in TIERS)
                if diff > SUPPLIED_SCORE_TOLERANCE:
                    issues.append(
                        {
                            "row": None,
                            "loc_id": asset.loc_id,
                            "severity": "warning",
                            "code": "supplied_scores_differ",
                            "message": f"Supplied hazard scores differ from the hazard maps by up to {diff:.3f}; map values used",
                        }
                    )
            tag = (
                nearest_hotspot(asset.lat, asset.lon, hotspots, config)
                if hotspots
                else None
            )
            if imd_on:
                terrain = baseline
                index, parts = index_value(
                    imd.components(asset.lat, asset.lon), config.imd_index
                )
                baseline = uplift(terrain, index, config.imd_index)
                tag = {
                    **(tag or {}),
                    "terrain_score": terrain,
                    "imd_index": round(index, 4),
                }
                if any(baseline[t] - terrain[t] > 1e-12 for t in TIERS):
                    imd_changes[asset.loc_id] = {
                        "imd_index": index,
                        "components": parts,
                        "terrain": terrain,
                        "adjusted": baseline,
                    }
            if ai_adjustment:
                signal = evidence_signal(asset.lat, asset.lon, applied, config)
                enriched = enhance(baseline, signal, config)
                changed = any(abs(enriched[t] - baseline[t]) > 1e-12 for t in TIERS)
                changes.append((asset, changed))
                if changed:
                    signals[asset.loc_id] = {
                        "evidence_signal": signal,
                        "baseline": baseline,
                        "adjusted": enriched,
                    }
            for tier in TIERS:
                row = property_loss(asset, baseline[tier], config, tag)
                if imd_on:
                    row["terrain_score"] = terrain[tier]
                    terrain_only[tier] += Decimal(
                        property_loss(asset, terrain[tier], config)["loss_kes"]
                    )
                results["baseline"][tier].append(row)
                if ai_adjustment:
                    results["enhanced"][tier].append(
                        property_loss(asset, enriched[tier], config, tag)
                    )
            hazard_ok.append(asset)
        except ModelError as exc:
            excluded.append(asset.loc_id)
            issues.append(
                {
                    "row": None,
                    "loc_id": asset.loc_id,
                    "severity": "error",
                    "code": exc.code,
                    "message": str(exc),
                }
            )
    has_errors = any(i["severity"] == "error" for i in issues)
    if has_errors and not allow_partial:
        raise ReviewRequired(issues, len(hazard_ok))
    if not hazard_ok:
        raise (
            ReviewRequired(issues, 0)
            if has_errors
            else ModelError(
                "no_modelled_assets", "No property has complete usable inputs"
            )
        )
    accepted_tiv = sum((a.tiv_kes for a in assets), Decimal(0))
    covered_tiv = sum((a.tiv_kes for a in hazard_ok), Decimal(0))
    runs = {}
    for name, scenarios in results.items():
        totals = {t: total_loss(r) for t, r in scenarios.items()}
        runs[name] = {
            "ep_curve": ep_curve(totals, config, covered_tiv),
            "aal": average_annual_loss(totals, config),
            "property_losses": scenarios,
            "breakdowns": {t: group_losses(r, config) for t, r in scenarios.items()},
        }
        if config.policy_terms["enabled"]:
            insured = {
                t: total_loss(r, "insured_loss_kes") for t, r in scenarios.items()
            }
            runs[name]["insured"] = {
                "ep_curve": ep_curve(insured, config, covered_tiv),
                "aal": average_annual_loss(insured, config),
                "terms": dict(config.policy_terms),
                "note": "Per-risk deductible and limit; reinsurance is shown separately",
            }
        if config.reinsurance["enabled"]:
            basis = "insured" if config.policy_terms["enabled"] else "gross"
            basis_totals = insured if basis == "insured" else totals
            runs[name]["reinsurance"] = reinsurance_programme(
                basis_totals, config.reinsurance, covered_tiv, basis, config
            )
        runs[name]["property_aal"] = property_aal(scenarios, config)
    contribution = {
        "enabled": ai_adjustment,
        "applied_evidence_count": len(applied),
        "approved_evidence_count": sum(e.approved for e in evidence),
        "changed_properties": sum(c for _, c in changes),
        "spread": spread(changes, hotspots, config)
        if ai_adjustment and hotspots
        else None,
        "property_changes": signals,
        "approved_evidence_snapshot": [e.to_dict() for e in applied],
        "note": "Increased loss does not by itself prove improved accuracy; see the hotspot comparison.",
    }
    if ai_adjustment:
        contribution["loss_delta_kes"] = {
            t: money_string(
                total_loss(results["enhanced"][t]) - total_loss(results["baseline"][t])
            )
            for t in TIERS
        }
        contribution["aal_delta_kes"] = money_string(
            Decimal(runs["enhanced"]["aal"]["aal_kes"])
            - Decimal(runs["baseline"]["aal"]["aal_kes"])
        )
    imd_summary = {"enabled": imd_on}
    if imd_on:
        base_totals = {t: total_loss(results["baseline"][t]) for t in TIERS}
        terrain_aal = Decimal(average_annual_loss(terrain_only, config)["aal_kes"])
        imd_summary.update(
            {
                "changed_properties": len(imd_changes),
                "property_changes": imd_changes,
                "terrain_only_loss_kes": {
                    t: money_string(terrain_only[t]) for t in TIERS
                },
                "loss_delta_kes": {
                    t: money_string(base_totals[t] - terrain_only[t]) for t in TIERS
                },
                "terrain_only_aal_kes": money_string(terrain_aal),
                "aal_delta_kes": money_string(
                    Decimal(runs["baseline"]["aal"]["aal_kes"]) - terrain_aal
                ),
                "grid": dict(getattr(imd, "meta", {}) or {}),
                "note": "Proxy for runoff pressure from OpenStreetMap building footprints; it does not observe drains or maintenance.",
            }
        )
    input_fingerprint = hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()
    ).hexdigest()
    return {
        "input_fingerprint": input_fingerprint,
        "hazard_provider": type(provider).__name__,
        "analysis_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "currency": "KES",
        "input_count": len(rows),
        "accepted_count": len(assets),
        "modelled_count": len(hazard_ok),
        "rejected_count": len(rows) - len(assets),
        "excluded_from_hazard": excluded,
        "accepted_tiv_kes": money_string(accepted_tiv),
        "modelled_tiv_kes": money_string(covered_tiv),
        "unmodelled_accepted_tiv_kes": money_string(accepted_tiv - covered_tiv),
        "partial": has_errors,
        "issues": issues,
        "runs": runs,
        "ai_contribution": contribution,
        "imd_adjustment": imd_summary,
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint,
        "exposure_origin": exposure_origin(hazard_ok),
        "provenance": provenance(config, exposure_origin(hazard_ok)),
        "limitations": [
            "Scenario EP points and AAL use assumed return periods, not a calibrated annual loss distribution.",
            (
                "Insured loss applies a simple per-property deductible and limit."
                if config.policy_terms["enabled"]
                else "Losses are gross of policy terms; no deductible or limit is applied."
            ),
            (
                "Reinsured loss uses an illustrative programme (quota share, then a per-event excess-of-loss layer), "
                "not a real treaty; no reinstatements, aggregate covers or multiple events per year."
                if config.reinsurance["enabled"]
                else "No reinsurance is applied."
            ),
            "Depth = score × max_depth_m is an assumption; the score is relative susceptibility, not measured depth.",
            "The JRC Africa residential curve rests on South African and Mozambican functions only; class scales and caps are assumptions.",
            "A zero score means the proxy did not flag the location, not that it cannot flood (drainage-driven flooding is invisible to it).",
        ]
        + (
            [
                "The infrastructure-deficit index raises hazard where OpenStreetMap shows dense, mostly roofed ground; it does not observe drains or maintenance, omits roads and paved yards, and reads unmapped areas as empty."
            ]
            if imd_on
            else []
        ),
        "hotspot_tagging": {
            "enabled": bool(hotspots),
            "hotspot_count": len(hotspots),
            "radius_m": config.hotspot_tag_radius_m,
        },
    }
