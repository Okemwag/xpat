"""Underwriting recommendation: accept, take a smaller share, or decline — from the model output, the offered terms and the
organisation's own rules.

Deterministic and explainable: every outcome comes from named rule checks with the numbers that triggered them. The AI may
explain a recommendation (`ai/decision.py`) but never sets it, and a person records the final decision
(`platform/data.record_decision`).

Price: technical premium (100%) = modelled AAL × (1 + uncertainty load) / target loss ratio. The offered premium divided by it
is the price adequacy. Capacity: our share of the 1-in-PML loss and of insured value must stay within the organisation's
maximum. All rule values are organisation choices (ASSUMPTION); starter values in `configs/underwriting_rules.json`.
"""
import json
import math
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from ..core.errors import ModelError

RULES_PATH = Path(__file__).resolve().parents[3]/'configs'/'underwriting_rules.json'
OUTCOMES = ('accept', 'share', 'decline')
OUTCOME_LABEL = {'accept': 'Accept the offered share', 'share': 'Take a smaller share', 'decline': 'Decline'}
# name: (lowest, highest, plain-English meaning) — bounds keep rules sensible, not market guidance.
RULE_SPEC = {
    'target_loss_ratio': (0.05, 1.5, 'Expected loss as a share of premium the organisation aims for'),
    'uncertainty_load': (0.0, 5.0, 'Extra loading on the modelled annual loss because the model is uncalibrated'),
    'decline_below_adequacy': (0.0, 1.0, 'Decline when the offered premium is below this share of the technical premium'),
    'marginal_share_factor': (0.0, 1.0, 'When the price is adequate but below technical, write at most this share of the offered line'),
    'pml_return_period': (2, 10000, 'Return period of the loss used to size our line (PML)'),
    'max_pml_kes': (1, 1e15, 'Largest share of the PML loss we hold on one submission (KES)'),
    'max_line_tiv_kes': (1, 1e16, 'Largest share of insured value we write on one submission (KES)'),
    'min_share_pct': (0.0, 100.0, 'A share smaller than this is not worth writing (%)'),
    'max_unmodelled_pct': (0.0, 100.0, 'Decline when more than this share of submitted records could not be modelled (%)'),
    'share_step_pct': (0.01, 10.0, 'Shares are rounded down to a multiple of this (%)'),
}

def default_rules():
    with open(RULES_PATH) as stream:
        return validate_rules({k: v for k, v in json.load(stream).items() if not k.startswith('_')})

def validate_rules(rules):
    """Complete, typed and bounded rules or a ModelError naming the problem."""
    if not isinstance(rules, dict) or set(rules) != set(RULE_SPEC):
        missing, extra = set(RULE_SPEC)-set(rules or {}), set(rules or {})-set(RULE_SPEC)
        raise ModelError('invalid_rules', 'Underwriting rules: ' + '; '.join(
            ([f"missing {', '.join(sorted(missing))}"] if missing else []) + ([f"unknown {', '.join(sorted(extra))}"] if extra else [])))
    out = {}
    for key, (low, high, meaning) in RULE_SPEC.items():
        try: value = float(rules[key])
        except (TypeError, ValueError): raise ModelError('invalid_rules', f'{meaning}: enter a number') from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ModelError('invalid_rules', f'{meaning}: must be between {low:g} and {high:g}')
        out[key] = value
    return out

def _d(value):
    return Decimal(str(value))

def _kes(value):
    v = _d(value); a = abs(v)
    if a >= 10**9: return f'KES {v/10**9:,.2f} bn'
    if a >= 10**6: return f'KES {v/10**6:,.1f} m'
    return f'KES {v:,.0f}'

def _floor_step(pct, step):
    step = _d(step)
    return float((_d(pct)/step).to_integral_value(ROUND_FLOOR)*step)

def model_view(report, run=None, basis=None):
    """The figures the rules use, read from an analysis: which run (AI-adjusted when present), gross or insured basis."""
    run = run or ('enhanced' if 'enhanced' in report['runs'] else 'baseline')
    if run not in report['runs']: raise ModelError('invalid', f'This analysis has no {run} run')
    source = report['runs'][run]
    basis = basis or ('insured' if 'insured' in source else 'gross')
    if basis == 'insured':
        if 'insured' not in source: raise ModelError('invalid', 'This analysis has no insured loss (policy terms were off)')
        source = source['insured']
    curve = sorted(source['ep_curve'], key=lambda p: p['return_period_years'])
    return {'run': run, 'basis': basis, 'aal_kes': _d(source['aal']['aal_kes']), 'tiv_kes': _d(report['modelled_tiv_kes']),
            'curve': [(float(p['return_period_years']), _d(p['loss_kes'])) for p in curve],
            'input_count': int(report.get('input_count') or report['modelled_count']), 'modelled_count': int(report['modelled_count']),
            'origin': list(report.get('exposure_origin', {}).get('labels', ['SYNTHETIC']))}

def _pml(view, rp):
    """Loss at the requested return period: exact scenario if modelled, else the nearest rarer one (or the rarest available)."""
    rarer = [(r, l) for r, l in view['curve'] if r >= rp]
    r, loss = rarer[0] if rarer else view['curve'][-1]
    return r, loss

def recommend(report, premium_100_kes, offered_share_pct, rules=None, run=None, basis=None):
    """Recommendation for writing `offered_share_pct` % of a risk whose 100% premium is `premium_100_kes`.

    Returns outcome, recommended share, the figures used and one check per rule (status pass / limit / fail)."""
    rules = validate_rules(rules) if rules is not None else default_rules()
    try:
        premium = _d(premium_100_kes); offered = float(offered_share_pct)
    except Exception:
        raise ModelError('invalid', 'Enter the premium and the share as numbers') from None
    if not premium.is_finite() or premium <= 0: raise ModelError('invalid', 'The offered premium must be above zero')
    if not math.isfinite(offered) or not 0 < offered <= 100: raise ModelError('invalid', 'The offered share must be above 0% and at most 100%')
    view = model_view(report, run, basis)
    aal, tiv = view['aal_kes'], view['tiv_kes']
    pml_rp, pml = _pml(view, rules['pml_return_period'])
    technical = aal*_d(1+rules['uncertainty_load'])/_d(rules['target_loss_ratio'])
    adequacy = float(premium/technical) if technical > 0 else None
    checks, caps = [], [('offered', offered)]

    # Price
    if adequacy is None:
        checks.append({'code': 'price', 'label': 'Price adequacy', 'status': 'pass', 'value': None, 'threshold': 1.0,
                       'detail': 'The model shows no annual loss for this risk, so price cannot be tested against it. '
                                 'Zero modelled loss means the hazard map did not flag these locations, not that they cannot flood.'})
    elif adequacy >= 1:
        checks.append({'code': 'price', 'label': 'Price adequacy', 'status': 'pass', 'value': adequacy, 'threshold': 1.0,
                       'detail': f'Offered premium {_kes(premium)} is {adequacy:.0%} of the technical premium {_kes(technical)}.'})
    elif adequacy >= rules['decline_below_adequacy']:
        cap = offered*rules['marginal_share_factor']
        caps.append(('price', cap))
        checks.append({'code': 'price', 'label': 'Price adequacy', 'status': 'limit', 'value': adequacy, 'threshold': 1.0,
                       'detail': f"Offered premium is {adequacy:.0%} of technical ({_kes(technical)}): adequate but thin, so the rules allow at most "
                                 f"{rules['marginal_share_factor']:.0%} of the offered share ({cap:.1f}%)."})
    else:
        checks.append({'code': 'price', 'label': 'Price adequacy', 'status': 'fail', 'value': adequacy, 'threshold': rules['decline_below_adequacy'],
                       'detail': f"Offered premium is {adequacy:.0%} of technical ({_kes(technical)}), below the decline threshold of "
                                 f"{rules['decline_below_adequacy']:.0%}."})

    # Capacity: PML and line size
    for code, label, amount, limit, what in (('pml', f'Share of the 1-in-{pml_rp:g} loss', pml, rules['max_pml_kes'], f'1-in-{pml_rp:g} loss'),
                                             ('line', 'Share of insured value', tiv, rules['max_line_tiv_kes'], 'insured value')):
        ours = amount*_d(offered)/100
        if amount <= 0 or ours <= _d(limit):
            checks.append({'code': code, 'label': label, 'status': 'pass', 'value': float(ours), 'threshold': limit,
                           'detail': f'At {offered:g}% our {what} is {_kes(ours)}, within the maximum of {_kes(limit)}.'})
        else:
            cap = float(_d(limit)/amount*100)
            caps.append((code, cap))
            checks.append({'code': code, 'label': label, 'status': 'limit', 'value': float(ours), 'threshold': limit,
                           'detail': f'At {offered:g}% our {what} would be {_kes(ours)}, above the maximum of {_kes(limit)}; '
                                     f'the largest share within it is {cap:.1f}%.'})

    # Data completeness
    unmodelled = 100*(view['input_count']-view['modelled_count'])/view['input_count'] if view['input_count'] else 0.0
    checks.append({'code': 'data', 'label': 'Records modelled', 'status': 'fail' if unmodelled > rules['max_unmodelled_pct'] else 'pass',
                   'value': unmodelled, 'threshold': rules['max_unmodelled_pct'],
                   'detail': f"{view['modelled_count']} of {view['input_count']} submitted records modelled ({unmodelled:.0f}% not modelled; "
                             f"maximum {rules['max_unmodelled_pct']:g}%)."})

    limit_names = {'offered': 'Offered share', 'price': 'Price rule', 'pml': f'1-in-{pml_rp:g} loss limit', 'line': 'Insured value limit'}
    share_limits = [{'rule': limit_names[code], 'max_share_pct': cap} for code, cap in caps]
    share = _floor_step(min(c for _, c in caps), rules['share_step_pct'])
    if any(c['status'] == 'fail' for c in checks):
        outcome, share = 'decline', 0.0
    elif share < rules['min_share_pct'] or share <= 0:
        outcome = 'decline'
        checks.append({'code': 'min_share', 'label': 'Minimum share', 'status': 'fail', 'value': share, 'threshold': rules['min_share_pct'],
                       'detail': f"The largest share within the rules ({share:g}%) is below the minimum worth writing ({rules['min_share_pct']:g}%)."})
        share = 0.0
    elif share < offered:
        outcome = 'share'
    else:
        outcome, share = 'accept', offered
    binding = [c['label'] for c in checks if c['status'] in ('fail', 'limit')]
    ours = _d(share)/100
    return {'outcome': outcome, 'outcome_label': OUTCOME_LABEL[outcome], 'recommended_share_pct': share, 'offered_share_pct': offered,
            'premium_100_kes': str(premium), 'run': view['run'], 'basis': view['basis'], 'origin': view['origin'],
            'figures': {'aal_100_kes': str(aal), 'pml_return_period': pml_rp, 'pml_100_kes': str(pml), 'tiv_100_kes': str(tiv),
                        'technical_premium_100_kes': str(technical.quantize(Decimal(1))), 'price_adequacy': adequacy,
                        'expected_loss_ratio': float(aal/premium), 'our_premium_kes': str((premium*ours).quantize(Decimal(1))),
                        'our_aal_kes': str((aal*ours).quantize(Decimal(1))), 'our_pml_kes': str((pml*ours).quantize(Decimal(1))),
                        'our_tiv_kes': str((tiv*ours).quantize(Decimal(1))), 'unmodelled_pct': unmodelled},
            'checks': checks, 'binding_rules': binding, 'share_limits': share_limits, 'rules': rules,
            'note': 'Indicative: built on a proxy hazard, assumed return periods and uncalibrated damage curves. A person makes the decision.'}
