"""Simple per-risk policy terms (ASSUMPTION, off by default). No layers, treaties or reinsurance.

insured loss = min(max(gross − deductible, 0), limit − deductible) per property, where the limit is
the maximum the policy pays before the deductible is applied. A row's own deductible_kes / limit_kes
override the portfolio-wide percentages of TIV from config; a row's deductible_pct_of_loss makes the
deductible a share of each loss, with deductible_kes as its minimum.
"""

from decimal import Decimal


def terms(asset, config):
    pct = config.policy_terms
    deductible = (
        asset.deductible_kes
        if asset.deductible_kes is not None
        else asset.tiv_kes * Decimal(str(pct["deductible_pct_of_tiv"]))
    )
    limit = (
        asset.limit_kes
        if asset.limit_kes is not None
        else asset.tiv_kes * Decimal(str(pct["limit_pct_of_tiv"]))
    )
    return deductible, limit


def split(ground_up, asset, config):
    """Ground-up loss = deductible borne by the owner + amount above the limit + gross loss (what the insurer pays).

    Returns (deductible_part, above_limit_part, gross_loss); the three add up to the ground-up loss.
    """
    paid = insured_loss(ground_up, asset, config)
    _, limit = terms(asset, config)
    above = max(Decimal(0), ground_up - limit) if paid > 0 else Decimal(0)
    return ground_up - paid - above, above, paid


def insured_loss(gross, asset, config):
    """A row with deductible_pct_of_loss uses max(pct × loss, deductible_kes) — "5% of loss, minimum KES 5m"."""
    deductible, limit = terms(asset, config)
    if asset.deductible_pct_of_loss is not None:
        deductible = max(
            gross * Decimal(str(asset.deductible_pct_of_loss)),
            asset.deductible_kes or Decimal(0),
        )
    return min(max(gross - deductible, Decimal(0)), max(limit - deductible, Decimal(0)))
