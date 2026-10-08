"""Plain-English Markdown summary of one analysis, for download and sharing."""
from decimal import Decimal
from ..core.constants import TIERS

def _kes(value):
    return f'KES {Decimal(str(value)):,.0f}'

def markdown_summary(report, ranges=None, ylt=None):
    cfg = report['config']
    run = report['runs']['baseline']
    curve = run['ep_curve']
    lines = [f"# Flood loss summary — {report['created_at'][:10]}", '',
             f"> Indicative, uncalibrated model: {' + '.join(report.get('exposure_origin', {}).get('labels', ['SYNTHETIC']))} exposure, PROXY hazard, ASSUMED return periods. "
             + ('Gross loss plus insured loss after simple per-property terms.' if 'insured' in run else 'Gross loss, no policy terms.'), '',
             f"- Properties modelled: {report['modelled_count']} of {report['input_count']} supplied",
             f"- Insured value modelled: {_kes(report['modelled_tiv_kes'])}",
             f"- Average annual loss: {_kes(run['aal']['aal_kes'])}", '',
             '| Return period | Annual chance | Loss | % of insured value |', '|---|---|---|---|']
    lines += [f"| 1-in-{p['return_period_years']:g} | {p['annual_exceedance_probability']:.1%} | {_kes(p['loss_kes'])} | "
              f"{'—' if p['loss_pct_of_tiv'] is None else format(p['loss_pct_of_tiv'], '.2f') + '%'} |" for p in curve]
    if 'insured' in run:
        t = run['insured']['terms']
        lines += ['', f"## Insured loss (deductible {t['deductible_pct_of_tiv']:.1%}, limit {t['limit_pct_of_tiv']:.0%} of value)", '',
                  f"- Insured average annual loss: {_kes(run['insured']['aal']['aal_kes'])}", '',
                  '| Return period | Insured loss |', '|---|---|']
        lines += [f"| 1-in-{p['return_period_years']:g} | {_kes(p['loss_kes'])} |" for p in run['insured']['ep_curve']]
    if ylt:
        y = ylt['baseline']['gross']; low, high = y['band_pct']
        lines += ['', f"## Loss curve from {y['years']:,} simulated years", '', f'| Rarity | Loss | Simulation range ({low:g}–{high:g}th pct) |', '|---|---|---|']
        lines += [f"| 1-in-{p['return_period_years']:,.0f} | {_kes(p['loss_kes'])} | {_kes(p['band_low_kes'])} – {_kes(p['band_high_kes'])} |" for p in y['table']]
        lines += ['', f"Simulated average annual loss {_kes(y['aal']['aal_kes'])}. {y['note']}"]
    if ranges:
        sim = ranges['baseline']['gross']; low, high = sim['interval_pct']
        lines += ['', f"## Damage-uncertainty range per scenario ({low:g}th–{high:g}th percentile)", '',
                  '| Return period | Low | Median | High |', '|---|---|---|---|']
        lines += [f"| 1-in-{s['return_period_years']:g} | {_kes(s['p_low_kes'])} | {_kes(s['median_kes'])} | {_kes(s['p_high_kes'])} |" for s in sim['by_tier'].values()]
        lines += ['', f"Average annual loss {_kes(sim['aal']['p_low_kes'])} – {_kes(sim['aal']['p_high_kes'])}. "
                  f"σ={sim['damage_sigma']:g}, ρ={sim['correlation']:g}, {sim['trials']} trials (ASSUMPTIONS)."]
    rarest = TIERS[-1]
    lines += ['', f"## Loss by construction (1-in-{cfg['return_periods'][rarest]:g})", '']
    lines += [f"- {c['id']}: {_kes(c['loss_kes'])} ({c['loss_share_pct']:.1f}%)" for c in run['breakdowns'][rarest]['construction']]
    if 'hotspot_area' in run['breakdowns'][rarest]:
        lines += ['', '## Largest concentrations near named hotspots', '']
        lines += [f"- {a['id']}: {_kes(a['loss_kes'])} from {a['property_count']} properties" for a in run['breakdowns'][rarest]['hotspot_area'][:5]]
    ai = report['ai_contribution']
    if ai['enabled']:
        lines += ['', '## AI drainage evidence', '',
                  f"{ai['applied_evidence_count']} approved report(s) raised hazard at {ai['changed_properties']} properties; "
                  f"average annual loss changed by {_kes(ai['aal_delta_kes'])}. A higher loss is not by itself proof of a better model."]
    if report['partial']:
        lines += ['', f"**Partial run:** {report['rejected_count'] + len(report['excluded_from_hazard'])} record(s) excluded."]
    lines += ['', '## Key assumptions', '',
              f"- Tier → return period: " + ', '.join(f"{t} {cfg['return_periods'][t]:g} yr" for t in TIERS),
              f"- Depth = hazard score × {cfg['max_depth_m']:g} m",
              f"- Damage curve: {cfg['vulnerability_source']}",
              f"- AAL: no loss below 1-in-{cfg['aal_zero_loss_return_period']:g}; rarest loss held beyond the last tier", '',
              '## Limitations', ''] + [f'- {item}' for item in report['limitations']]
    lines += ['', f"Config {cfg['version']} · fingerprint {report['config_fingerprint'][:12]} · analysis {report['analysis_id']}"]
    return '\n'.join(lines)+'\n'
