"""Simple per-risk policy terms (ASSUMPTION, off by default). No layers, treaties or reinsurance.

insured loss = min(max(gross − deductible, 0), limit − deductible) per property, where the limit is
the maximum the policy pays before the deductible is applied. A row's own deductible_kes / limit_kes
override the portfolio-wide percentages of TIV from config.
"""
from decimal import Decimal

def terms(asset, config):
    pct = config.policy_terms
    deductible = asset.deductible_kes if asset.deductible_kes is not None else asset.tiv_kes*Decimal(str(pct['deductible_pct_of_tiv']))
    limit = asset.limit_kes if asset.limit_kes is not None else asset.tiv_kes*Decimal(str(pct['limit_pct_of_tiv']))
    return deductible, limit

def insured_loss(gross, asset, config):
    deductible, limit = terms(asset, config)
    return min(max(gross-deductible, Decimal(0)), max(limit-deductible, Decimal(0)))
