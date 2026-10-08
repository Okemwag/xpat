"""Content of the downloadable analysis report, independent of file format.

`build_document` turns one analysis (plus, when available, the simulated loss curve, damage-uncertainty ranges, the AI
briefing and recorded underwriting decisions) into a list of blocks. `reporting/formats.py` renders the same blocks as
PDF, Word or Excel, so the three downloads always say the same thing. Every section carries its provenance labels
(AGENTS.md §5). Table cells hold raw values with a column format, so Excel keeps numbers as numbers.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from ..core.constants import TIERS

CLASS_LABEL = {'informal_iron_sheet': 'Informal (iron sheet)', 'semi_permanent': 'Semi-permanent',
               'permanent_masonry': 'Permanent masonry', 'concrete_rcc': 'Reinforced concrete'}
OUTCOME_WORDS = {'accept': 'Accept', 'share': 'Take a smaller share', 'decline': 'Decline'}

@dataclass
class Table:
    title: str
    columns: list                 # [(header, fmt)]; fmt: text | kes | pct (value in %) | ratio (0–1) | rp | int | num
    rows: list
    note: str = ''
    labels: tuple = ()
    sheet: str = ''               # Excel sheet name; tables sharing a name go on one sheet
    data_only: bool = False       # Excel only (too long for PDF/Word)

@dataclass
class Document:
    title: str
    subtitle: str
    meta: list                    # [(label, value)]
    blocks: list = field(default_factory=list)

def kes(value, compact=True):
    v = Decimal(str(value))
    if not compact: return f'KES {v:,.0f}'
    a = abs(v)
    if a >= 10**9: return f'KES {v/10**9:,.2f} bn'
    if a >= 10**6: return f'KES {v/10**6:,.1f} m'
    if a >= 10**3: return f'KES {v/10**3:,.0f} k'
    return f'KES {v:,.0f}'

def fmt(value, kind):
    """Display text for one cell (PDF and Word)."""
    if value is None or value == '': return '—'
    if kind == 'kes': return kes(value, compact=False)
    if kind == 'pct': return f'{float(value):.2f}%'
    if kind == 'ratio': return f'{float(value):.1%}'
    if kind == 'rp': return f'1-in-{float(value):,.0f}'
    if kind == 'int': return f'{int(value):,}'
    if kind == 'num': return f'{float(value):.3f}'
    return str(value)

def _origin(report):
    return list(report.get('exposure_origin', {}).get('labels', ['SYNTHETIC']))

def build_document(report, *, label='Analysis', organisation='', author='', ylt=None, ranges=None, briefing=None, decisions=(),
                   generated_at=None):
    cfg = report['config']; base = report['runs']['baseline']; origin = _origin(report)
    generated_at = generated_at or datetime.now(timezone.utc)
    curve = {p['return_period_years']: p for p in base['ep_curve']}
    rps = sorted(curve); rarest = rps[-1]; mid = 100.0 if 100.0 in curve else rps[len(rps)//2]
    rarest_tier = TIERS[-1]; mid_tier = next(t for t in TIERS if cfg['return_periods'][t] == mid)
    doc = Document(f'Flood loss report — {label}', organisation or 'Xpat · Nairobi urban flood model',
                   [('Generated', generated_at.strftime('%d %b %Y %H:%M UTC')), ('Prepared by', author or '—'),
                    ('Analysis', report['analysis_id']), ('Analysis run', str(report['created_at'])[:16].replace('T', ' ')),
                    ('Model configuration', f"{cfg['version']} · {report['config_fingerprint'][:12]}"),
                    ('Exposure', ' + '.join(origin) + f" · {report['modelled_count']} of {report['input_count']} records modelled")])
    add = doc.blocks.append

    add(('callout', 'Indicative results from an uncalibrated model: ' + ' + '.join(origin) + ' exposure, a PROXY hazard map (terrain and rivers, '
         'blind to drainage), ASSUMED return periods and adapted published damage curves. Not a price and not underwriting advice. '
         + ('Losses are gross and, where shown, insured after simple per-property terms.' if 'insured' in base else 'Losses are gross (no policy terms).')))
    add(('heading', 'Headline figures', 1, ('ASSUMPTION', 'PROXY', *origin)))
    kpis = [('Insured value modelled', kes(report['modelled_tiv_kes']), f"{report['modelled_count']} properties"),
            (f'1-in-{mid:g} loss', kes(curve[mid]['loss_kes']), f"{curve[mid]['loss_pct_of_tiv']:.2f}% of value" if curve[mid]['loss_pct_of_tiv'] is not None else ''),
            (f'1-in-{rarest:g} loss', kes(curve[rarest]['loss_kes']), f"{curve[rarest]['loss_pct_of_tiv']:.2f}% of value" if curve[rarest]['loss_pct_of_tiv'] is not None else ''),
            ('Average annual loss', kes(base['aal']['aal_kes']), 'Long-run yearly average from the curve')]
    if 'insured' in base: kpis.append(('Insured average annual loss', kes(base['insured']['aal']['aal_kes']), 'After policy terms'))
    add(('kpis', kpis))
    add(('para', f"A “1-in-{mid:g}” loss is one with an assumed {1/mid:.1%} chance of being reached or exceeded in any year. Return periods are "
         'assumptions mapped to the five hazard tiers: tier names describe how extreme a map cell is, not how often it floods.'))

    # Loss curve
    add(('heading', 'Loss against rarity (EP curve)', 1, ('PROXY', 'ASSUMPTION', *origin)))
    add(('chart', 'ep', 'Portfolio loss reached or exceeded by a year’s worst flood. Diamonds: the five hazard scenarios'
         + ('; line and grey band: 10,000 simulated years and their re-sampling range.' if ylt else '.')))
    add(Table('The five hazard scenarios', [('Return period', 'rp'), ('Tier', 'text'), ('Annual chance', 'ratio'), ('Loss', 'kes'), ('% of insured value', 'pct')]
              + ([('Insured loss', 'kes')] if 'insured' in base else []),
              [[p['return_period_years'], p['tier'], p['annual_exceedance_probability'], p['loss_kes'], p['loss_pct_of_tiv']]
               + ([next(q['loss_kes'] for q in base['insured']['ep_curve'] if q['tier'] == p['tier'])] if 'insured' in base else [])
               for p in base['ep_curve']], labels=('ASSUMPTION',), sheet='Scenarios'))
    if ylt:
        y = ylt['baseline']['gross']; low, high = y['band_pct']
        add(Table(f"Simulated loss curve ({y['years']:,} years)", [('Return period', 'rp'), ('Loss', 'kes'), (f'Range low ({low:g}th pct)', 'kes'),
                                                                   (f'Range high ({high:g}th pct)', 'kes'), ('Modelled from', 'text')],
                  [[p['return_period_years'], p['loss_kes'], p['band_low_kes'], p['band_high_kes'],
                    'hazard tiers' if p['return_period_years'] <= y['rarest_modelled_return_period'] else 'damage uncertainty only'] for p in y['table']],
                  note=f"Simulated average annual loss {kes(y['aal']['aal_kes'])}. The range is a re-sampling of simulated years, not a confidence interval. "
                       f"Beyond 1-in-{y['rarest_modelled_return_period']:g} no rarer flood is modelled; only damage uncertainty varies.",
                  labels=('ASSUMPTION',), sheet='Simulated curve'))
    if ranges:
        sim = ranges['baseline']['gross']; low, high = sim['interval_pct']
        add(Table('Damage-uncertainty range per scenario', [('Return period', 'rp'), (f'Low ({low:g}th pct)', 'kes'), ('Median', 'kes'), (f'High ({high:g}th pct)', 'kes')],
                  [[s['return_period_years'], s['p_low_kes'], s['median_kes'], s['p_high_kes']] for s in sim['by_tier'].values()],
                  note=f"Monte Carlo on the damage ratio only (σ={sim['damage_sigma']:g}, ρ={sim['correlation']:g}, {sim['trials']} trials) — ASSUMPTIONS, "
                       'not a confidence interval.', labels=('ASSUMPTION',), sheet='Damage uncertainty'))

    # What drives it
    add(('heading', 'What drives the loss', 1, ('ASSUMPTION', *origin)))
    add(('chart', 'construction', f'Share of the 1-in-{rarest:g} loss by construction class.'))
    add(Table(f'Loss by construction (1-in-{mid:g} and 1-in-{rarest:g})',
              [('Construction', 'text'), ('Properties', 'int'), ('Insured value', 'kes'), (f'Loss 1-in-{mid:g}', 'kes'), (f'Loss 1-in-{rarest:g}', 'kes'),
               ('Share of rarest loss', 'pct')],
              [[CLASS_LABEL.get(c['id'], c['id']), c['property_count'], c['tiv_kes'],
                next((m['loss_kes'] for m in base['breakdowns'][mid_tier]['construction'] if m['id'] == c['id']), 0), c['loss_kes'], c['loss_share_pct']]
               for c in base['breakdowns'][rarest_tier]['construction']], labels=('ASSUMPTION', *origin), sheet='Construction'))
    b = base['breakdowns'][rarest_tier]
    if b.get('hotspot_area'):
        add(Table(f"Where it concentrates: named flood areas (within {cfg['hotspot_tag_radius_m']/1000:g} km)",
                  [('Area', 'text'), ('Properties', 'int'), ('Insured value', 'kes'), (f'Loss 1-in-{rarest:g}', 'kes'), ('Share of loss', 'pct')],
                  [[a['id'] if not a['id'].startswith('no named') else 'Away from named areas', a['property_count'], a.get('tiv_kes'), a['loss_kes'], a['loss_share_pct']]
                   for a in b['hotspot_area'][:12]], note='Area names are real (county list); coordinates are approximate neighbourhood centres.',
                  labels=('REAL', 'ASSUMPTION'), sheet='Accumulation'))
    add(Table(f"Value and loss by {cfg['grid_size_m']/1000:g} km cell (top 10 by loss)",
              [('Cell', 'text'), ('Properties', 'int'), ('Insured value', 'kes'), (f'Loss 1-in-{rarest:g}', 'kes'), ('Share of loss', 'pct')],
              [[g['id'], g['property_count'], g['tiv_kes'], g['loss_kes'], g['loss_share_pct']] for g in b['geographic_grid'][:10]],
              labels=('ASSUMPTION', *origin), sheet='Accumulation'))
    add(Table(f'Largest property losses (1-in-{rarest:g})', [('Property', 'text'), ('Construction', 'text'), ('Insured value', 'kes'), ('Hazard score', 'num'),
                                                             ('Assumed depth (m)', 'num'), ('Damage ratio', 'ratio'), ('Loss', 'kes')],
              [[p['loc_id'], CLASS_LABEL.get(p['housing_class'], p['housing_class']), p['tiv_kes'], p['hazard_score'], p['assumed_depth_m'], p['damage_ratio'], p['loss_kes']]
               for p in b['top_properties'][:10]], note='Loss = insured value × damage ratio (× flood-exposed share for multi-storey buildings).',
              labels=('PROXY', 'ASSUMPTION', *origin), sheet='Top properties'))

    # AI
    ai = report['ai_contribution']
    if ai['enabled'] or briefing:
        add(('heading', 'AI contribution', 1, ('AI',)))
    if ai['enabled']:
        from ..ai.evaluation import describe_adjustment
        add(('para', f"{describe_adjustment(ai)} raised the hazard at {ai['changed_properties']} properties; "
             f"average annual loss changed by {kes(ai['aal_delta_kes'])}. A higher loss is not by itself evidence of a better model."))
        enh = report['runs']['enhanced']
        add(Table('Loss with and without the AI hazard adjustment', [('Return period', 'rp'), ('Baseline', 'kes'), ('With AI adjustment', 'kes')],
                  [[p['return_period_years'], p['loss_kes'], q['loss_kes']] for p, q in zip(base['ep_curve'], enh['ep_curve'])],
                  labels=('AI', 'ASSUMPTION'), sheet='AI evidence'))
    if briefing:
        add(('heading', f"AI underwriting briefing: {briefing['headline']}", 2, ('AI',)))
        add(('para', f"Drafted by {briefing['model']} ({briefing['prompt_version']}) from {briefing['fact_count']} model facts. Every figure was checked against "
             'the model output' + (f"; not found in the output: {', '.join(briefing['unsupported_figures'])}." if briefing['unsupported_figures'] else '.')))
        for s in briefing['sections']:
            add(('heading', s['heading'], 3, ()))
            for p in s['paragraphs']: add(('para', p))
        if briefing['checks']: add(('heading', 'Before relying on this result', 3, ())); add(('bullets', list(briefing['checks'])))

    # Underwriting decisions
    if decisions:
        add(('heading', 'Underwriting decisions recorded', 1, ('ASSUMPTION',)))
        add(Table('Decisions on this analysis', [('When', 'text'), ('Decided by', 'text'), ('Premium (100%)', 'kes'), ('Offered share', 'pct'),
                                                 ('Rules recommended', 'text'), ('Decision', 'text'), ('Share taken', 'pct'), ('Overrode rules', 'text'), ('Reason', 'text')],
                  [[str(d['created_at'])[:16], d.get('decided_by_name', ''), d['premium_100_kes'], float(d['offered_share_pct']),
                    OUTCOME_WORDS[d['recommendation']['outcome']] + (f" {d['recommendation']['recommended_share_pct']:g}%" if d['recommendation']['outcome'] == 'share' else ''),
                    OUTCOME_WORDS[d['outcome']], float(d['share_pct']), 'yes' if d['overrode'] else 'no', d.get('reason') or ''] for d in decisions],
                  note='The rules recommend; a person decides. Rule values are the organisation’s own (ASSUMPTION).', labels=('ASSUMPTION',), sheet='Decisions'))

    # Assumptions, provenance, limitations
    add(('heading', 'Assumptions and where every number comes from', 1, ('ASSUMPTION',)))
    add(Table('Key assumptions', [('Assumption', 'text'), ('Value', 'text')],
              [['Tier → return period', ', '.join(f"{t} 1-in-{cfg['return_periods'][t]:g}" for t in TIERS)],
               ['Hazard score → depth', f"depth = score × {cfg['max_depth_m']:g} m"],
               ['Damage curve', cfg['vulnerability_source']],
               ['Class adjustments', '; '.join(f"{CLASS_LABEL[c]}: depth scale {v['jrc_depth_scale']:g}, cap {v['damage_cap']:.0%}" for c, v in cfg['class_adjustments'].items())],
               ['Average annual loss', f"no loss below 1-in-{cfg['aal_zero_loss_return_period']:g}; rarest loss held beyond the last tier"],
               ['Policy terms', (f"deductible {cfg['policy_terms']['deductible_pct_of_tiv']:.1%}, limit {cfg['policy_terms']['limit_pct_of_tiv']:.0%} of value per property"
                                 if cfg['policy_terms']['enabled'] else 'off — gross loss')]], labels=('ASSUMPTION',), sheet='Assumptions'))
    add(Table('Provenance', [('Component', 'text'), ('Label', 'text'), ('Detail', 'text')],
              [[p['component'].replace('_', ' '), p['label'], p['note']] for p in report['provenance']], labels=('REAL', 'PROXY', 'SYNTHETIC', 'ASSUMPTION', 'AI'),
              sheet='Provenance'))
    add(('heading', 'Limitations', 2, ()))
    add(('bullets', list(report['limitations'])))
    if report['partial']:
        add(('para', f"Partial run: {report['rejected_count'] + len(report['excluded_from_hazard'])} record(s) could not be modelled and are excluded."))

    # Data appendix (Excel)
    for run in report['runs']:
        for t in TIERS:
            add(Table(f"Property losses — {'AI-adjusted' if run == 'enhanced' else 'baseline'} — 1-in-{cfg['return_periods'][t]:g} ({t})",
                      [('Property', 'text'), ('Latitude', 'num'), ('Longitude', 'num'), ('Construction', 'text'), ('Insured value', 'kes'), ('Hazard score', 'num'),
                       ('Assumed depth (m)', 'num'), ('Damage ratio', 'ratio'), ('Flood-exposed share', 'ratio'), ('Loss', 'kes'), ('Synthetic', 'text'), ('Source', 'text')],
                      [[r['loc_id'], r['lat'], r['lon'], r['housing_class'], r['tiv_kes'], r['hazard_score'], r['assumed_depth_m'], r['damage_ratio'],
                        r.get('exposed_fraction', 1.0), r['loss_kes'], 'true' if r.get('synthetic', True) else 'false', r.get('exposure_source', '')]
                       for r in report['runs'][run]['property_losses'][t]],
                      labels=('PROXY', 'ASSUMPTION', *origin), sheet=f"Props {'AI' if run == 'enhanced' else 'base'} {t}", data_only=True))
    return doc
