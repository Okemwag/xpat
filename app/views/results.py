import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from ui import state
from ui.charts import class_bars, ylt_chart
from ui.components import explain, page_header, pipeline_strip, require_result, run_banner, tier_selector

page_header('Loss curve', 'How large a loss to expect at each level of flood rarity — from 10,000 simulated years.')
pipeline_strip('Loss curve')
report = require_result()
run_banner(report)
cfg = state.config()
runs = ['baseline'] + (['enhanced'] if 'enhanced' in report['runs'] else [])
run = 'baseline'
basis = 'gross'
with st.container(horizontal=True, vertical_alignment='bottom'):
    if len(runs) > 1:
        run = st.segmented_control('Model', runs, default='baseline', format_func={'baseline': 'Baseline', 'enhanced': 'With AI evidence'}.get) or 'baseline'
    if 'insured' in report['runs'][run]:
        basis = st.segmented_control('Loss basis', ['gross', 'insured'], default='insured',
                                     format_func={'gross': 'Gross (ground-up)', 'insured': 'Insured (after policy terms)'}.get) or 'insured'
try:
    with st.spinner('Simulating 10,000 years…'): curves = state.ylt(report)
except ModelError as exc:
    st.error(str(exc)); st.stop()
sim = curves[run]['insured' if basis == 'insured' else 'gross']
low, high = sim['band_pct']
rarest = sim['rarest_modelled_return_period']

st.altair_chart(ylt_chart(curves, report, compare_ai=len(runs) > 1, basis=basis), width='stretch')
explain(f'The {basis} portfolio loss that a year’s worst flood would reach or exceed, for rarities from 1-in-1 to 1-in-10,000 years. '
        f'Diamonds are the five hazard scenarios the simulation is built from; the grey band is the {low:g}th–{high:g}th percentile range from '
        f're-sampling the simulated years.',
        'Pick a point on the horizontal axis: “1-in-100” means a loss at least this large has about a 1% chance in any single year — not that it '
        f'happens once a century. Left of the dashed line (1-in-{rarest:g}) is modelled from hazard tiers; right of it, only damage uncertainty varies.',
        ['PROXY', 'ASSUMPTION', 'SYNTHETIC'], source='hazard tiers (proxy) · assumed return periods · adapted JRC curves · synthetic portfolio ·')

table = pd.DataFrame([{'Rarity': f"1-in-{p['return_period_years']:,.0f}", 'Annual chance': f"{p['annual_exceedance_probability']:.2%}",
                       'In plain words': state.rp_sentence(p['return_period_years'], p['loss_kes']),
                       f'Simulation range ({low:g}–{high:g}th pct)': f"{state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])}",
                       'Modelled from': 'hazard tiers' if p['return_period_years'] <= rarest else 'extrapolated (damage uncertainty only)'}
                      for p in sim['table']])
st.dataframe(table, hide_index=True, width='stretch')

with st.container(border=True):
    st.markdown(f"**Average annual loss ({basis}): {state.kes(sim['aal']['aal_kes'], compact=False)}** · range "
                f"{state.kes(sim['aal']['band_low_kes'])} – {state.kes(sim['aal']['band_high_kes'])}")
    st.caption(f"The mean of {sim['years']:,} simulated years ({sim['zero_loss_years']:,} of them with no loss, because floods more frequent than "
               f"1-in-{cfg.aal_zero_loss_return_period:g} are assumed to cause none). ASSUMPTION — not a calibrated annual loss.")
    if basis == 'insured':
        t = report['runs'][run]['insured']['terms']
        st.caption(f"Policy terms: deductible {t['deductible_pct_of_tiv']:.1%}, limit {t['limit_pct_of_tiv']:.0%} of insured value per property "
                   '(or the row’s own deductible_kes / limit_kes). No layers or reinsurance.')

with st.expander('The five scenario points behind the curve, and their damage-uncertainty ranges'):
    source = report['runs'][run] if basis == 'gross' else report['runs'][run]['insured']
    try: damage = state.uncertainty(report)[run]['insured' if basis == 'insured' else 'gross']
    except ModelError: damage = None
    st.dataframe(pd.DataFrame([{'Tier': p['tier'], 'Assumed rarity': state.rp_label(p['return_period_years']),
                                'Scenario loss': state.kes(p['loss_kes'], compact=False), '% of insured value': state.pct(p['loss_pct_of_tiv']),
                                **({'If damage curves are uncertain': f"{state.kes(damage['by_tier'][p['tier']]['p_low_kes'])} – {state.kes(damage['by_tier'][p['tier']]['p_high_kes'])}"} if damage else {})}
                               for p in source['ep_curve']]), hide_index=True, width='stretch')
    if damage:
        st.caption(f"Damage-uncertainty range: {damage['interval_pct'][0]:g}th–{damage['interval_pct'][1]:g}th percentile of {damage['trials']:,} draws, "
                   f"σ={damage['damage_sigma']:g}, portfolio-wide correlation ρ={damage['correlation']:g} (ASSUMPTIONS). It answers “how wrong could "
                   'this one scenario be if the damage curves are off?”. The grey band on the curve answers a different question: how much the '
                   'simulated curve moves with a different sample of 10,000 years.')
    st.caption('Each tier is run once through hazard → damage → loss. The tier names describe how extreme a map cell is, not how often it '
               'floods: “extreme” (narrowest footprint) is the most frequent event, “common” (widest) the rarest.')

st.subheader('Breakdown for one flood')
tier, rp = tier_selector('results_tier')
b = report['runs'][run]['breakdowns'][tier]
st.altair_chart(class_bars(b['construction']), width='stretch')
explain(f'Gross loss by construction class in the {state.rp_label(rp)} scenario.',
        'Longer bars lose more money; the label is each class’s share of the total. Value, not fragility, drives most of the loss here.',
        ['SYNTHETIC', 'ASSUMPTION'])
