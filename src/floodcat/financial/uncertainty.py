"""Monte Carlo ranges for damage-ratio uncertainty (ASSUMPTION). Requires numpy.

Only the damage ratio is uncertain here: hazard, return periods and insured values are held fixed,
so the ranges show how much the answer depends on the vulnerability curve, not total model error.

For trial k and property b, with z = √ρ·Z_k + √(1−ρ)·ε_kb (Z, ε standard normal):
    ratio_kb,t = min(cap_b, mean_b,t · exp(σ·z − σ²/2))
The same z applies to every tier of a property in a trial (one curve error per building), so each
simulated loss curve still rises with rarity. ρ is the share of the error common to the whole
portfolio (curve-level error); without it, 600 independent errors would cancel and hide most of the
uncertainty. Mean-preserving before the cap; the cap trims the upper tail slightly.
"""
from decimal import Decimal
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import money_string
from .policy import terms

CHUNK = 250

def simulate_losses(run, assets_by_id, config, insured=False):
    """Raw simulated portfolio losses: array of trials × tiers (numpy)."""
    try:
        import numpy as np
    except ImportError:
        raise ModelError('uncertainty_unavailable', 'Install numpy (geo or ui extra) to estimate uncertainty ranges') from None
    u = config.uncertainty
    rows = run['property_losses'][TIERS[0]]
    ids = [r['loc_id'] for r in rows]
    by_tier = {t: {r['loc_id']: r for r in run['property_losses'][t]} for t in TIERS}
    mean = np.array([[by_tier[t][i]['damage_ratio'] for t in TIERS] for i in ids])
    tiv = np.array([float(by_tier[TIERS[0]][i]['tiv_kes'])*by_tier[TIERS[0]][i].get('exposed_fraction', 1.0) for i in ids])
    cap = np.array([config.class_adjustments[by_tier[TIERS[0]][i]['housing_class']]['damage_cap'] for i in ids])
    if insured:
        pairs = [terms(assets_by_id[i], config) for i in ids]
        pct = np.array([assets_by_id[i].deductible_pct_of_loss or 0.0 for i in ids])
        minimum = np.array([float(assets_by_id[i].deductible_kes or 0) if assets_by_id[i].deductible_pct_of_loss is not None else float(d)
                            for i, (d, _) in zip(ids, pairs)])
        limit = np.array([float(l) for _, l in pairs])
    sigma, rho = u['damage_sigma'], u['correlation']
    rng = np.random.default_rng(u['seed'])
    losses = []
    for start in range(0, u['trials'], CHUNK):
        n = min(CHUNK, u['trials']-start)
        z = np.sqrt(rho)*rng.standard_normal((n, 1)) + np.sqrt(1-rho)*rng.standard_normal((n, len(ids)))
        factor = np.exp(sigma*z - sigma**2/2)[:, :, None]                     # trials × properties × 1
        ratio = np.minimum(mean[None, :, :]*factor, cap[None, :, None])       # trials × properties × tiers
        gross = ratio*tiv[None, :, None]
        if insured:
            deductible = np.maximum(gross*pct[None, :, None], minimum[None, :, None])
            gross = np.minimum(np.maximum(gross-deductible, 0), np.maximum(limit[None, :, None]-deductible, 0))
        losses.append(gross.sum(axis=1))                                      # trials × tiers
    return np.vstack(losses)

def simulate(run, assets_by_id, config, insured=False):
    import numpy as np
    u = config.uncertainty
    losses = simulate_losses(run, assets_by_id, config, insured)
    sigma, rho = u['damage_sigma'], u['correlation']
    rps = np.array([config.return_periods[t] for t in TIERS])
    aep = np.concatenate([[1/config.aal_zero_loss_return_period], 1/rps])
    curves = np.hstack([np.zeros((len(losses), 1)), losses])
    aal = ((aep[:-1]-aep[1:])*(curves[:, :-1]+curves[:, 1:])/2).sum(axis=1) + aep[-1]*curves[:, -1]
    low, high = u['interval_pct']
    def summary(values):
        return {'mean_kes': money_string(Decimal(str(float(values.mean())))), 'p_low_kes': money_string(Decimal(str(float(np.percentile(values, low))))),
                'median_kes': money_string(Decimal(str(float(np.median(values))))), 'p_high_kes': money_string(Decimal(str(float(np.percentile(values, high)))))}
    return {'trials': u['trials'], 'damage_sigma': sigma, 'correlation': rho, 'seed': u['seed'], 'interval_pct': [low, high],
            'basis': 'insured' if insured else 'gross',
            'by_tier': {t: {'return_period_years': config.return_periods[t], **summary(losses[:, i])} for i, t in enumerate(TIERS)},
            'aal': summary(aal), 'status': 'assumed_uncalibrated',
            'note': 'Damage-ratio uncertainty only; hazard, frequency and values are held fixed. Not a confidence interval on the true loss.'}

def uncertainty_ranges(report, rows, config):
    """Ranges for a finished analysis. `rows` are the prepared input rows (needed only for policy terms)."""
    from ..exposure.validation import validate_rows
    assets_by_id = {a.loc_id: a for a in validate_rows(rows)[0]} if config.policy_terms['enabled'] else {}
    result = {}
    for name, run in report['runs'].items():
        result[name] = {'gross': simulate(run, assets_by_id, config)}
        if config.policy_terms['enabled']: result[name]['insured'] = simulate(run, assets_by_id, config, insured=True)
    return result
