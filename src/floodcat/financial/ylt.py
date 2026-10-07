"""Simulated year-loss table (YLT) and the EP curve read from it. Requires numpy.

Each simulated year draws
  * how rare that year's worst flood is: an annual exceedance probability u ~ Uniform(0, 1), and
  * one damage-uncertainty trial k (a simulated loss curve from financial/uncertainty.py).
The year's loss is trial k's scenario loss curve read at u, interpolated linearly in annual
exceedance probability between the five tier points — the same rule as the AAL — with no loss
below the zero-loss return period and the rarest tier's loss held for rarer years (ASSUMPTIONS).
So the YLT mean equals the AAL of the mean curve, and the YLT adds frequency sampling on top of the
damage uncertainty. Bootstrapping the simulated years gives the band.

Beyond the rarest tier (1-in-250 by default) the model has no hazard information: the curve keeps
rising only because of damage uncertainty, not because rarer floods are modelled.
"""
from decimal import Decimal
from ..core.constants import TIERS
from ..core.numeric import money_string
from .uncertainty import simulate_losses

REPORT_RPS = (2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000)

def _money(value):
    return money_string(Decimal(str(float(value))))

def year_losses(trial_losses, config, rng):
    import numpy as np
    years = config.year_loss_table['years']
    rps = [config.return_periods[t] for t in TIERS]
    # Ascending AEP: rarest tier first, the zero-loss point last.
    xp = np.array([1/rp for rp in reversed(rps)]+[1/config.aal_zero_loss_return_period])
    fp = np.hstack([trial_losses[:, ::-1], np.zeros((len(trial_losses), 1))])
    u = rng.random(years)
    k = rng.integers(len(trial_losses), size=years)
    j = np.searchsorted(xp, u, side='right')
    lo = np.clip(j-1, 0, len(xp)-1); hi = np.clip(j, 0, len(xp)-1)
    w = np.where(hi > lo, (u-xp[lo])/np.where(hi > lo, xp[hi]-xp[lo], 1), 0)
    loss = fp[k, lo]+w*(fp[k, hi]-fp[k, lo])
    loss = np.where(j == 0, fp[k, 0], loss)              # rarer than the rarest tier: hold its loss
    return np.where(j >= len(xp), 0.0, loss)               # more frequent than the zero-loss point

def ep_from_ylt(losses, config, rng):
    import numpy as np
    cfg = config.year_loss_table
    years = len(losses)
    rps = np.array([rp for rp in REPORT_RPS if rp <= years], dtype=float)
    curve_rps = np.unique(np.concatenate([np.geomspace(1, years, 80), rps]))
    quantile = lambda values, grid: np.quantile(values, np.clip(1-1/grid, 0, 1), method='linear')
    boot = rng.integers(years, size=(cfg['bootstrap'], years))
    samples = losses[boot]
    low, high = cfg['band_pct']
    boot_curve = np.array([quantile(s, curve_rps) for s in samples])
    boot_aal = samples.mean(axis=1)
    curve = quantile(losses, curve_rps)
    points = [{'return_period_years': float(rp), 'annual_exceedance_probability': 1/rp,
               'loss_kes': _money(v), 'band_low_kes': _money(lo_), 'band_high_kes': _money(hi_)}
              for rp, v, lo_, hi_ in zip(curve_rps, curve, np.percentile(boot_curve, low, axis=0), np.percentile(boot_curve, high, axis=0))]
    table = {float(rp): p for rp in rps for p in points if p['return_period_years'] == float(rp)}
    return {'curve': points, 'table': [table[float(rp)] for rp in rps],
            'aal': {'aal_kes': _money(losses.mean()), 'band_low_kes': _money(np.percentile(boot_aal, low)),
                    'band_high_kes': _money(np.percentile(boot_aal, high))}}

def simulate_ylt(run, assets_by_id, config, insured=False):
    import numpy as np
    cfg = config.year_loss_table
    rng = np.random.default_rng(cfg['seed'])
    losses = year_losses(simulate_losses(run, assets_by_id, config, insured), config, rng)
    result = ep_from_ylt(losses, config, rng)
    rarest = max(config.return_periods.values())
    result.update(years=cfg['years'], bootstrap=cfg['bootstrap'], band_pct=list(cfg['band_pct']), basis='insured' if insured else 'gross',
                  zero_loss_years=int((losses == 0).sum()), rarest_modelled_return_period=rarest, status='assumed_uncalibrated',
                  note=f'Simulated from five assumed scenario points; beyond 1-in-{rarest:g} only damage uncertainty varies, no rarer floods are modelled.')
    return result

def ylt_for_report(report, rows, config):
    from ..exposure.validation import validate_rows
    assets_by_id = {a.loc_id: a for a in validate_rows(rows)[0]} if config.policy_terms['enabled'] else {}
    out = {}
    for name, run in report['runs'].items():
        out[name] = {'gross': simulate_ylt(run, assets_by_id, config)}
        if config.policy_terms['enabled']: out[name]['insured'] = simulate_ylt(run, assets_by_id, config, insured=True)
    return out
