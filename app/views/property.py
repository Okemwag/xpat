from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES, TIERS
from ui import state
from ui.charts import columns_chart, vulnerability_chart
from ui.components import explain, kpis, page_header, pipeline_strip, require_result, run_banner, section

page_header('Property explorer', 'Trace any property’s loss back to its inputs: value, location, hazard score, assumed depth and damage curve.')
pipeline_strip('Financial engine')
report = require_result()
run_banner(report)
cfg = state.config()
runs = ['baseline'] + (['enhanced'] if 'enhanced' in report['runs'] else [])
rarest = TIERS[-1]

with st.container(horizontal=True, vertical_alignment='bottom'):
    classes = st.pills('Construction', list(CLASSES), selection_mode='multi', default=list(CLASSES), format_func=state.class_label, key='prop_classes')
    run = (st.segmented_control('Model', runs, default='baseline', format_func={'baseline': 'Baseline', 'enhanced': 'With AI evidence'}.get, key='prop_run')
           if len(runs) > 1 else 'baseline') or 'baseline'
    only_loss = st.toggle('Only properties with a loss', value=False, key='prop_only_loss')
by_id = {t: {r['loc_id']: r for r in report['runs'][run]['property_losses'][t]} for t in TIERS}
ordered = sorted((r for r in by_id[rarest].values() if r['housing_class'] in (classes or CLASSES) and (not only_loss or Decimal(r['loss_kes']) > 0)),
                 key=lambda r: -float(r['loss_kes']))
if not ordered:
    st.info('No property matches these filters.', icon=':material/filter_alt_off:'); st.stop()
choice = st.selectbox(f'Property ({len(ordered)} shown, largest loss first)', [r['loc_id'] for r in ordered], index=0,
                      format_func=lambda i: f"{i} · {state.class_label(by_id[rarest][i]['housing_class'])} · {state.kes(by_id[rarest][i]['loss_kes'])} at {state.rp_label(cfg.return_periods[rarest])}")
p = by_id[rarest][choice]
rank = [r['loc_id'] for r in sorted(by_id[rarest].values(), key=lambda r: -float(r['loss_kes']))].index(choice)+1
share = Decimal(p['loss_kes'])/Decimal(p['tiv_kes']) if Decimal(p['tiv_kes']) else Decimal(0)
kpis([('Insured value', state.kes(p['tiv_kes']), 'SYNTHETIC' if p.get('synthetic', True) else 'REAL'),
      ('Construction', state.class_label(p['housing_class'])),
      (f'{state.rp_label(cfg.return_periods[rarest])} loss', state.kes(p['loss_kes']), f'Rank {rank} of {len(by_id[rarest])} by loss', f'{share:.1%} of value'),
      ('Nearest named hotspot', p.get('nearest_hotspot') or '—', None, f"{p['hotspot_distance_m']/1000:.1f} km away" if p.get('nearest_hotspot') else None)])

rows = []
for t in TIERS:
    r = by_id[t][choice]
    rows.append({'Return period': state.rp_label(cfg.return_periods[t]), 'Tier': t, 'Hazard score': r['hazard_score'], 'Depth (m)': r['assumed_depth_m'],
                 'Damage ratio': r['damage_ratio'], 'Loss (KES m)': round(float(r['loss_kes'])/1e6, 3), 'Loss': state.kes(r['loss_kes'], compact=False)})
frame = pd.DataFrame(rows)
left, right = st.columns([3, 2], gap='large')
with left.container(border=True, height='stretch'):
    section('From hazard to loss', 'One bar per hazard scenario, from most frequent to rarest')
    chart = columns_chart([{'Scenario': r['Return period'], 'Loss (KES m)': r['Loss (KES m)'], 'Loss': r['Loss'], 'Damage': f"{r['Damage ratio']:.1%}"} for r in rows],
                          'Scenario', 'Loss (KES m)', 'Loss (KES m)', sort=None)
    st.altair_chart(chart, width='stretch', alt=f'Loss of property {choice} in each hazard scenario')
    last = rows[-1]
    exposed = p.get('exposed_fraction', 1)
    st.markdown(f"**At {last['Return period']}:** score {last['Hazard score']:.3f} × {cfg.max_depth_m:g} m = {last['Depth (m)']:.2f} m of water "
                f"→ {last['Damage ratio']:.1%} damaged → {state.kes(p['tiv_kes'])} × {last['Damage ratio']:.1%}"
                + (f" × {exposed:.0%} flood-exposed share (basements + lowest storey)" if exposed < 1 else '') + f" = **{last['Loss']}**")
    explain('This property’s loss in each of the five hazard scenarios.',
            'Taller bar = bigger loss. Losses grow with rarity because a rarer scenario flags more of the map and scores this location higher.',
            ['PROXY', 'ASSUMPTION', 'REAL' if not p.get('synthetic', True) else 'SYNTHETIC'],
            source='hazard score (proxy) · depth = score × max depth (assumption) · class damage curve (adapted JRC) · insured value as supplied')
with right.container(border=True, height='stretch'):
    section('Where it sits on the damage curve', state.class_label(p['housing_class']))
    st.altair_chart(vulnerability_chart(cfg, marks=frame[['Return period', 'Depth (m)', 'Damage ratio']]), width='stretch',
                    alt='Damage curves by construction class with this property’s five scenarios marked')
    explain('All four class curves; orange points are this property in the five scenarios.',
            'Further right = deeper assumed water; height = share of value damaged. The dashed line is the depth at a score of 1.', ['REAL', 'ASSUMPTION'])

if all(r['Hazard score'] == 0 for r in rows):
    st.info('The proxy map does not flag this location in any tier, so it has no modelled loss. That does not mean it cannot '
            'flood — drainage failures are invisible to the proxy.', icon=':material/info:')
ai = report['ai_contribution']
if ai['enabled'] and choice in ai['property_changes']:
    change = ai['property_changes'][choice]
    why = ' and '.join(x for x in (f"evidence signal {change['evidence_signal']:.2f}" if change['evidence_signal'] else '',
                                   f"drainage-model signal {change.get('drainage_signal', 0):.2f}" if change.get('drainage_signal') else '') if x)
    st.success(f"The AI hazard adjustment raised this property's hazard ({why}): common-tier score "
               f"{change['baseline']['common']:.3f} → {change['adjusted']['common']:.3f}.", icon=':material/auto_awesome:')

a, b = st.columns([3, 2], gap='large')
with a.container(border=True, height='stretch'):
    section('Every scenario')
    st.dataframe(frame.drop(columns=['Loss (KES m)']), hide_index=True, width='stretch', alt=f'Hazard, depth, damage and loss for {choice} in each scenario',
                 column_config={'Hazard score': st.column_config.ProgressColumn(format='%.3f', min_value=0, max_value=1),
                                'Depth (m)': st.column_config.NumberColumn(format='%.2f'), 'Damage ratio': st.column_config.NumberColumn(format='percent')})
    if p.get('exposure_source'): st.caption(f"Source: {p['exposure_source']}")
with b.container(border=True, height='stretch'):
    section('Location', f"{p['lat']:.4f}, {p['lon']:.4f}")
    st.map(pd.DataFrame({'lat': [p['lat']], 'lon': [p['lon']]}), size=120, color='#eb6834', zoom=13, height=260)
