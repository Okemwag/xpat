import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES, TIERS
from floodcat.core.errors import ModelError
from floodcat.services.sensitivity import assumption_sensitivity
from floodcat.vulnerability.functions import matrix
from ui import state
from ui.charts import vulnerability_chart
from ui.components import badges, page_header

page_header('Assumptions & sensitivity', 'Every modelling choice is visible here. Change one, re-run, and see how much the answer moves.', ('ASSUMPTION',))
base = state.runtime().config
current = state.config()

with st.form('assumptions'):
    st.subheader('Hazard interpretation')
    max_depth = st.slider('Depth at a hazard score of 1 (m)', 0.5, 4.0, float(current.max_depth_m), 0.1,
                          help='Pluvial flooding in Nairobi is typically 0.3–1.5 m; the brief\'s example uses 4 m.')
    st.markdown('**Assumed return period for each tier** (must increase from extreme to common)')
    cols = st.columns(5)
    rps = {t: cols[i].number_input(t, min_value=1.0, max_value=10000.0, value=float(current.return_periods[t]), step=5.0, key=f'rp_{t}')
           for i, t in enumerate(TIERS)}
    st.subheader('Vulnerability (per construction class)')
    adj = {}
    for c in CLASSES:
        a, b, l = st.columns([2, 2, 3])
        l.markdown(f'**{state.class_label(c)}**')
        adj[c] = {'jrc_depth_scale': a.number_input('JRC depth scale', 0.1, 3.0, float(current.class_adjustments[c]['jrc_depth_scale']), 0.05, key=f's_{c}'),
                  'damage_cap': b.slider('Damage cap', 0.80, 0.95, float(current.class_adjustments[c]['damage_cap']), 0.01, key=f'c_{c}')}
    st.subheader('Annual loss & accumulation')
    a, b = st.columns(2)
    zero = a.number_input('No loss below a 1-in-X event', 1.0, 9.9, float(current.aal_zero_loss_return_period), 0.5)
    radius = b.number_input('Hotspot grouping radius (m)', 250.0, 10000.0, float(current.hotspot_tag_radius_m), 250.0)
    apply = st.form_submit_button('Apply and re-run', type='primary', icon=':material/refresh:')
if apply:
    overrides = {'max_depth_m': max_depth, 'return_periods': rps, 'class_adjustments': adj, 'aal_zero_loss_return_period': zero, 'hotspot_tag_radius_m': radius}
    changed = {k: v for k, v in overrides.items() if v != getattr(base, k)}
    try:
        base.replace(**changed)
        st.session_state['config_overrides'] = changed
        if state.result():
            settings = st.session_state.get('run_settings', {})
            _, error = state.execute(st.session_state['rows'], st.session_state.get('run_label', 'Run') + ' (custom assumptions)',
                                     settings={**settings, 'allow_partial': True})
            if error: st.error(str(error))
        st.success('Assumptions applied.' + (' Results updated.' if state.result() else ' Run a portfolio to see results.'))
    except ModelError as exc:
        st.error(str(exc))
if st.session_state.get('config_overrides') and st.button('Reset to the documented defaults', icon=':material/restart_alt:'):
    st.session_state.pop('config_overrides')
    if state.result():
        settings = st.session_state.get('run_settings', {})
        state.execute(st.session_state['rows'], st.session_state.get('run_label', 'Run').replace(' (custom assumptions)', ''), settings=settings)
    st.rerun()

cfg = state.config()
st.subheader('Damage curves in use')
st.altair_chart(vulnerability_chart(cfg), width='stretch')
m = matrix(cfg)
st.markdown('**Vulnerability matrix** (damage ratio by hazard score and class)')
st.dataframe(pd.DataFrame({'Hazard score': m['scores'], 'Assumed depth (m)': m['assumed_depth_m'],
                           **{state.class_label(c): m['damage_ratio'][c] for c in CLASSES}}), hide_index=True, width='stretch',
             column_config={state.class_label(c): st.column_config.NumberColumn(format='percent') for c in CLASSES})
badges('REAL', 'ASSUMPTION')
st.caption(cfg.vulnerability_source)

st.subheader('Sensitivity of the current portfolio')
if not state.result():
    st.info('Run a portfolio to see how its losses respond to each assumption.')
else:
    if st.button('Run sensitivity scenarios', icon=':material/science:'):
        with st.spinner('Re-running the portfolio under each scenario…'):
            rows, settings = st.session_state['rows'], st.session_state.get('run_settings', {})
            from floodcat.exposure.validation import apply_declarations
            prepared, _ = apply_declarations(rows, settings.get('declare_synthetic', False), settings.get('source_label'), settings.get('assign_missing_ids', False))
            st.session_state['sensitivity'] = assumption_sensitivity(prepared, cfg, state.runtime().hazard)
    sens = st.session_state.get('sensitivity')
    if sens:
        names = {'base': 'Current assumptions', 'area_times_cost_tiv': 'Insured value = area × cost/m²', 'doubled_return_periods': 'All return periods doubled'}
        st.dataframe(pd.DataFrame([{'Scenario': names.get(k, k.replace('max_depth_', 'Max depth ').replace('m', ' m')),
                                    **{state.rp_label(cfg.return_periods[t]): state.kes(v['loss_kes_by_tier'][t]) for t in TIERS},
                                    'Average annual loss': state.kes(v['aal_kes'])} for k, v in sens['cases'].items()]),
                     hide_index=True, width='stretch')
        for note in sens['notes']: st.caption(note)
        st.caption('These are assumption scenarios, not confidence intervals.')
