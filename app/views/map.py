from decimal import Decimal
import pandas as pd
import streamlit as st
from floodcat.ai.evidence import usable
from ui import state
from ui.charts import portfolio_map
from ui.components import explain, page_header, pipeline_strip, require_result, run_banner, tier_selector

page_header('Exposure, hazard and accumulation', 'Every property on the map: its value, its flood score and the loss they produce together.')
pipeline_strip('Hazard')
report = require_result()
run_banner(report)
cfg = state.config()
c1, c2 = st.columns([2, 1])
with c1: tier, rp = tier_selector('map_tier')
with c2:
    runs = ['baseline'] + (['enhanced'] if 'enhanced' in report['runs'] else [])
    run = st.radio('Model', runs, horizontal=True, format_func={'baseline': 'Baseline', 'enhanced': 'With AI evidence'}.get) if len(runs) > 1 else 'baseline'

color_by = st.segmented_control('Colour properties by', ['score', 'loss'], default='score',
                                format_func={'score': 'Hazard score', 'loss': 'Loss'}.get) or 'score'
rows = report['runs'][run]['property_losses'][tier]
points = [{'lat': r['lat'], 'lon': r['lon'], 'loss': float(r['loss_kes']), 'tiv': float(r['tiv_kes']), 'score': r['hazard_score'],
           'tooltip': f"<b>{r['loc_id']}</b> · {state.class_label(r['housing_class'])}<br/>"
                      f"Insured value {state.kes(r['tiv_kes'])}<br/>"
                      f"Hazard score {r['hazard_score']:.3f} ({tier}, {state.rp_label(rp)}) → depth {r['assumed_depth_m']:.2f} m<br/>"
                      f"Damage ratio {r['damage_ratio']:.1%}<br/>"
                      f"<b>Loss = {state.kes(r['tiv_kes'])} × {r['damage_ratio']:.1%} = {state.kes(r['loss_kes'])}</b>"
                      + (f"<br/>Nearest hotspot: {r['nearest_hotspot']} ({r['hotspot_distance_m']/1000:.1f} km)" if r.get('nearest_hotspot') else '')}
          for r in rows]
evidence = usable(state.runtime().store.list_evidence(), cfg) if run == 'enhanced' else ()
st.pydeck_chart(portfolio_map(points, state.runtime().hotspots, evidence, color_by=color_by), height=540)
explain(f"All {len(points)} properties. Dot size = insured value; colour = {'hazard score (0–1)' if color_by == 'score' else 'loss'} at {state.rp_label(rp)} "
        '(light = none, dark blue = highest). Orange rings: the 24 government-named flood hotspots'
        + ('; purple circles: approved AI drainage evidence and its reach.' if evidence else '.'),
        'Hover a property to trace its loss: class → insured value → hazard score → depth → damage ratio → loss. Big dark dots close '
        'together are concentrations a single flood could hit at once. Grey dots are not flagged by the proxy — not proof they cannot flood.',
        ['SYNTHETIC', 'PROXY', 'REAL', 'ASSUMPTION'], source='synthetic properties · proxy hazard map · named hotspots (approximate) ·')

b = report['runs'][run]['breakdowns'][tier]
left, right = st.columns(2, gap='large')
with left:
    st.subheader('By named hotspot area')
    st.caption(f'Properties grouped under their nearest named hotspot if within {cfg.hotspot_tag_radius_m/1000:g} km.')
    st.dataframe(pd.DataFrame([{'Area': a['id'], 'Properties': a['property_count'], 'Insured value': state.kes(a['tiv_kes']),
                                'Loss': state.kes(a['loss_kes']), 'Share of loss': a['loss_share_pct']} for a in b['hotspot_area']]),
                 hide_index=True, width='stretch',
                 column_config={'Share of loss': st.column_config.ProgressColumn('Share of loss', format='%.1f%%', min_value=0, max_value=100)})
with right:
    st.subheader(f'By {cfg.grid_size_m/1000:g} km grid cell')
    st.caption('Top cells by loss. A cell is a co-location group, not an independent event.')
    total_tiv = sum(Decimal(r['tiv_kes']) for r in rows) or Decimal(1)
    st.dataframe(pd.DataFrame([{'Cell': g['id'], 'Properties': g['property_count'], 'Insured value': state.kes(g['tiv_kes']),
                                '% of portfolio value': float(Decimal(g['tiv_kes'])/total_tiv*100), 'Loss': state.kes(g['loss_kes'])}
                               for g in b['geographic_grid'][:15]]), hide_index=True, width='stretch',
                 column_config={'% of portfolio value': st.column_config.NumberColumn(format='%.1f%%')})
