import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from ui import state
from ui.charts import vulnerability_chart
from ui.components import explain, page_header, pipeline_strip, require_result, run_banner

page_header('Property explorer', 'Trace any loss back to its inputs: value, location, hazard score, assumed depth and damage curve.',
            ('PROXY', 'ASSUMPTION'))
pipeline_strip('Financial engine')
report = require_result()
run_banner(report)
cfg = state.config()
run = report['runs']['baseline']
by_id = {t: {r['loc_id']: r for r in run['property_losses'][t]} for t in TIERS}
rarest = TIERS[-1]
ordered = sorted(by_id[rarest].values(), key=lambda r: -float(r['loss_kes']))
ids = [r['loc_id'] for r in ordered]
choice = st.selectbox('Property (sorted by largest loss)', ids, index=0,
                      format_func=lambda i: f"{i} · {state.class_label(by_id[rarest][i]['housing_class'])} · {state.kes(by_id[rarest][i]['loss_kes'])} at {state.rp_label(cfg.return_periods[rarest])}")
p = by_id[rarest][choice]

a, b, c, d = st.columns(4)
a.metric('Insured value', state.kes(p['tiv_kes']), border=True)
b.metric('Construction', state.class_label(p['housing_class']), border=True)
c.metric('Nearest named hotspot', p.get('nearest_hotspot', '—'), border=True,
         help=f"{p.get('hotspot_distance_m', 0)/1000:.1f} km away" if p.get('nearest_hotspot') else None)
d.metric('Location', f"{p['lat']:.4f}, {p['lon']:.4f}", border=True)
if p.get('exposure_source'): st.caption(f"Source: {p['exposure_source']}")

rows = []
for t in TIERS:
    r = by_id[t][choice]
    rows.append({'Return period': state.rp_label(cfg.return_periods[t]), 'Tier': t, 'Hazard score': r['hazard_score'],
                 'Depth (m)': r['assumed_depth_m'], 'Damage ratio': r['damage_ratio'], 'Loss': state.kes(r['loss_kes'], compact=False)})
frame = pd.DataFrame(rows)
left, right = st.columns([3, 2], gap='large')
with left:
    st.subheader('From hazard to loss')
    st.dataframe(frame, hide_index=True, width='stretch',
                 column_config={'Hazard score': st.column_config.NumberColumn(format='%.3f'), 'Depth (m)': st.column_config.NumberColumn(format='%.2f'),
                                'Damage ratio': st.column_config.NumberColumn(format='percent')})
    last = rows[-1]
    st.markdown(f"**The calculation at {last['Return period']}:** score {last['Hazard score']:.3f} × {cfg.max_depth_m:g} m = "
                f"{last['Depth (m)']:.2f} m → {last['Damage ratio']:.1%} damage → {state.kes(p['tiv_kes'])} × {last['Damage ratio']:.1%}"
                + (f" × {p['exposed_fraction']:.0%} flood-exposed share (basements + lowest storey)" if p.get('exposed_fraction', 1) < 1 else '')
                + f" = **{last['Loss']}**")
    st.caption(f"Hazard score: PROXY · depth conversion and class curve: ASSUMPTION on a published JRC curve · value: {'REAL' if not p.get('synthetic', True) else 'SYNTHETIC'}.")
    if all(r['Hazard score'] == 0 for r in rows):
        st.info('The proxy map does not flag this location in any tier, so it has no modelled loss. That does not mean it cannot '
                'flood — drainage failures are invisible to the proxy.', icon=':material/info:')
    ai = report['ai_contribution']
    if ai['enabled'] and choice in ai['property_changes']:
        change = ai['property_changes'][choice]
        st.success(f"AI evidence raised this property's hazard (signal {change['evidence_signal']:.2f}): common-tier score "
                   f"{change['baseline']['common']:.3f} → {change['adjusted']['common']:.3f}.", icon=':material/auto_awesome:')
with right:
    st.subheader('Where it sits on the damage curve')
    marks = frame.rename(columns={'Return period': 'Return period'})[['Return period', 'Depth (m)', 'Damage ratio']]
    chart_cfg = cfg
    st.altair_chart(vulnerability_chart(chart_cfg, marks=marks), width='stretch')
    explain('This property’s class curve, with an orange point for each of the five scenarios.',
            'Further right = deeper assumed water in rarer floods; the height is the share of value damaged.', ['REAL', 'ASSUMPTION'])
