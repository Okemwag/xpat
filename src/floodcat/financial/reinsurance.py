"""Reinsurance: what a simple programme cedes and what the insurer keeps, per event (ASSUMPTION).

Programme, applied to each event's loss L (the insured loss when policy terms are on, otherwise gross):
  1. Quota share: the reinsurer takes a fixed share c of every loss.     QS = c·L
  2. Per-event excess of loss on the insurer's retained share:            XL = min(limit, max(0, (1 − c)·L − retention))
  ceded = QS + XL                    net retained = L − ceded
The excess-of-loss layer protects the insurer's net after the quota share (it "inures to the benefit" of the insurer),
the usual order for a cedant buying both. The retention and limit are set as shares of the modelled insured value so the
same structure scales to any uploaded portfolio, and are reported in KES.

Not modelled: reinstatements and their premiums, aggregate covers, multiple events in one year (each modelled year has
one worst flood), per-risk layers, reinsurance pricing and counterparty default.
"""

from decimal import Decimal
from ..core.errors import ModelError
from ..core.numeric import bounded, money_string


def validate_settings(s):
    need = {"enabled", "source", "quota_share_cession", "xol_retention_pct_of_tiv", "xol_limit_pct_of_tiv"}
    if not isinstance(s, dict) or set(s) != need or not isinstance(s["enabled"], bool):
        raise ModelError("invalid_config", "reinsurance needs " + ", ".join(sorted(need)))
    cession = bounded(s["quota_share_cession"], "quota_share_cession")
    retention = bounded(s["xol_retention_pct_of_tiv"], "xol_retention_pct_of_tiv")
    limit = bounded(s["xol_limit_pct_of_tiv"], "xol_limit_pct_of_tiv")
    if cession >= 1:
        raise ModelError("invalid_config", "A quota share must leave the insurer some share (cession below 100%)")
    if s["enabled"] and cession == 0 and limit == 0:
        raise ModelError("invalid_config", "Reinsurance is on but cedes nothing: set a quota share or an excess-of-loss limit")
    return {**s, "quota_share_cession": cession, "xol_retention_pct_of_tiv": retention, "xol_limit_pct_of_tiv": limit}


def layer_amounts(settings, tiv):
    """Retention and limit of the excess-of-loss layer in KES for a portfolio of insured value `tiv`."""
    tiv = Decimal(str(tiv))
    return (tiv * Decimal(str(settings["xol_retention_pct_of_tiv"])),
            tiv * Decimal(str(settings["xol_limit_pct_of_tiv"])))


def apply(loss, settings, tiv):
    """Split one event's loss (Decimal) into quota share, excess of loss, ceded and net."""
    loss = Decimal(str(loss))
    c = Decimal(str(settings["quota_share_cession"]))
    retention, limit = layer_amounts(settings, tiv)
    qs = loss * c
    xl = min(limit, max(Decimal(0), loss - qs - retention))
    return {"quota_share": qs, "excess_of_loss": xl, "ceded": qs + xl, "net": loss - qs - xl}


def apply_array(losses, settings, tiv):
    """Vectorised `apply` for simulated year losses (numpy floats): returns (ceded, net)."""
    import numpy as np

    c = settings["quota_share_cession"]
    retention, limit = (float(x) for x in layer_amounts(settings, tiv))
    qs = losses * c
    xl = np.minimum(limit, np.maximum(0.0, losses - qs - retention))
    return qs + xl, losses - qs - xl


def programme(totals, settings, tiv, basis, config):
    """Ceded and net loss per scenario, their EP points and AAL, and the programme in KES."""
    from .ep import average_annual_loss, ep_curve
    from ..core.constants import TIERS

    split = {t: apply(totals[t], settings, tiv) for t in TIERS}
    retention, limit = layer_amounts(settings, tiv)
    out = {
        "basis": basis,
        "structure": {
            "quota_share_cession": settings["quota_share_cession"],
            "xol_retention_kes": money_string(retention),
            "xol_limit_kes": money_string(limit),
            "xol_exhaustion_kes": money_string(
                (retention + limit) / (1 - Decimal(str(settings["quota_share_cession"])))
            ),
        },
        "by_tier": [
            {"tier": t, "return_period_years": config.return_periods[t], "loss_kes": money_string(totals[t]),
             **{k: money_string(v) for k, v in split[t].items()}}
            for t in TIERS
        ],
        "note": "Per event: quota share, then excess of loss on the insurer's retained share. No reinstatements, "
                "aggregate covers or multiple events per year. The AAL integrates each curve through the five points.",
    }
    for part in ("ceded", "net"):
        part_totals = {t: split[t][part] for t in TIERS}
        out[part] = {"ep_curve": ep_curve(part_totals, config, tiv), "aal": average_annual_loss(part_totals, config)}
    return out
