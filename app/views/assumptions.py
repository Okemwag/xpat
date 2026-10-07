import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES, TIERS
from floodcat.core.errors import ModelError
from floodcat.services.sensitivity import assumption_sensitivity
from floodcat.vulnerability.functions import matrix
from ui import state
from ui.charts import damage_vs_score_chart, vulnerability_chart
from ui.components import badges, explain, page_header, pipeline_strip

page_header('Vulnerability, assumptions & sensitivity', 'Every modelling choice is visible here. Change one, re-run, and see how much the answer moves.')
pipeline_strip('Vulnerability')
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
    st.subheader('Policy terms (optional)')
    st.caption('Per-property deductible and limit, giving an insured loss next to the gross loss. Rows with their own '
               '`deductible_kes` / `limit_kes` columns override these percentages. No layers or reinsurance (out of scope).')
    pt = current.policy_terms
    terms_on = st.toggle('Apply policy terms', value=pt['enabled'])
    a, b = st.columns(2)
    deductible = a.number_input('Deductible (% of insured value)', 0.0, 50.0, pt['deductible_pct_of_tiv']*100, 0.5)
    limit = b.number_input('Limit (% of insured value)', 1.0, 100.0, pt['limit_pct_of_tiv']*100, 5.0)
    st.subheader('Uncertainty ranges')
    st.caption('Monte Carlo on the damage ratio only. σ is the spread of each property\'s damage around the curve; '
               'correlation is the share of that error common to the whole portfolio (a curve that is wrong everywhere).')
    uc = current.uncertainty
    a, b, c = st.columns(3)
    sigma = a.slider('Damage spread σ (log scale)', 0.0, 1.0, float(uc['damage_sigma']), 0.05)
    rho = b.slider('Portfolio-wide correlation ρ', 0.0, 1.0, float(uc['correlation']), 0.05)
    trials = c.select_slider('Simulations', [500, 1000, 2000, 5000, 10000], value=uc['trials'] if uc['trials'] in (500, 1000, 2000, 5000, 10000) else 2000)
    apply = st.form_submit_button('Apply and re-run', type='primary', icon=':material/refresh:')
if apply:
    overrides = {'max_depth_m': max_depth, 'return_periods': rps, 'class_adjustments': adj, 'aal_zero_loss_return_period': zero, 'hotspot_tag_radius_m': radius,
                 'policy_terms': {'enabled': terms_on, 'deductible_pct_of_tiv': deductible/100, 'limit_pct_of_tiv': limit/100},
                 'uncertainty': {**uc, 'damage_sigma': sigma, 'correlation': rho, 'trials': trials}}
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
# Approximate damage at score 1 read from the reference dashboard in PROBLEM_STATEMENT.md, Figure 1 (display only).
REFERENCE_FIG1 = {'informal_iron_sheet': 0.85, 'semi_permanent': 0.69, 'permanent_masonry': 0.52, 'concrete_rcc': 0.31}
st.subheader('Damage matrix: damage ratio against hazard score')
st.altair_chart(damage_vs_score_chart(cfg, REFERENCE_FIG1), width='stretch')
explain(f'The share of a building\'s rebuild value damaged at each hazard score, one curve per construction class. Crosses mark the reference '
        'dashboard\'s values at a score of 1 (problem statement, Figure 1).',
        f'Move right along a curve: higher score → deeper assumed water (score × {cfg.max_depth_m:g} m) → more damage. Fragile classes rise '
        'faster. Hover for “X% of rebuild value damaged”.',
        ['REAL', 'ASSUMPTION'], source='JRC Africa residential curve (published) · class adjustments and max depth (ours) ·')
from floodcat.vulnerability.functions import damage_ratio
compare = pd.DataFrame([{'Class': state.class_label(c), 'Reference dashboard at score 1': REFERENCE_FIG1[c],
                         'Xpat at score 1': damage_ratio(1.0, c, cfg), 'Xpat damage cap': cfg.class_adjustments[c]['damage_cap']} for c in CLASSES])
st.dataframe(compare, hide_index=True, width='stretch', column_config={k: st.column_config.NumberColumn(format='percent') for k in
             ('Reference dashboard at score 1', 'Xpat at score 1', 'Xpat damage cap')})
_rcc_note = ''
if state.result():
    from decimal import Decimal
    _items = {i['id']: Decimal(i['tiv_kes']) for i in state.result()['runs']['baseline']['breakdowns']['common']['construction']}
    _share = _items.get('concrete_rcc', Decimal(0))/(sum(_items.values()) or Decimal(1))
    _rcc_note = f"In the current portfolio concrete holds {_share:.0%} of insured value, so this choice {'moves the portfolio loss more than any other vulnerability setting' if _share > Decimal('0.5') else 'matters in proportion to that share'} — try a lower RCC depth scale above to see by how much."
with st.expander('Why our curves differ from the reference dashboard'):
    st.markdown(f"""
- **Method.** The reference feeds the 0–1 score straight into a saturating curve. We convert score to an assumed depth
  (score × {cfg.max_depth_m:g} m) and read the published JRC Africa residential depth-damage curve, so the curve is sourced, not invented,
  and underwriters can reason in metres.
- **Fragile classes agree closely.** At a score of 1 we give informal iron-sheet {damage_ratio(1.0, 'informal_iron_sheet', cfg):.0%} (reference ≈85%)
  and masonry {damage_ratio(1.0, 'permanent_masonry', cfg):.0%} (≈52%).
- **Concrete is where we differ most:** {damage_ratio(1.0, 'concrete_rcc', cfg):.0%} vs ≈31%. We scale the JRC depth axis by 1.3 for RCC rather
  than imposing a low ceiling; the reference's 31% ceiling is itself a judgement call, below the brief's 80–95% cap guidance.
  {_rcc_note}
- **Caps.** Our caps (95/90/85/80%) follow the brief; at the base max depth they never bind, because 1.5 m is too shallow to reach them.
""")
st.subheader('Damage against depth (the JRC view)')
st.altair_chart(vulnerability_chart(cfg), width='stretch')
explain('The same curves against assumed flood depth in metres; the dashed line is the depth at a score of 1.',
        'Read up from a depth to the damage ratio for each class.', ['REAL', 'ASSUMPTION'])
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
