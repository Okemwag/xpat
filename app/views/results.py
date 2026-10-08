import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from ui import state
from ui.charts import class_bars, ylt_chart
from ui.charts import hbars
from ui.components import badges, explain, kpis, page_header, pipeline_strip, require_result, run_banner, section, tier_selector

page_header('Loss curve')
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

table = {int(p['return_period_years']): p for p in sim['table']}
def tile(rp):
    p = table.get(rp)
    return (f'1-in-{rp:,}', state.kes(p['loss_kes']), f"Simulation range {state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])}",
            f"{state.kes(p['band_low_kes'])}–{state.kes(p['band_high_kes'])}") if p else None
kpis([tile(10), tile(100), tile(250), tile(1000),
      ('Average annual loss', state.kes(sim['aal']['aal_kes']), 'Mean of the simulated years', f"{state.kes(sim['aal']['band_low_kes'])}–{state.kes(sim['aal']['band_high_kes'])}")])

with st.container(border=True):
    st.altair_chart(ylt_chart(curves, report, compare_ai=len(runs) > 1, basis=basis), width='stretch')
    explain(f'{basis.title()} loss reached or exceeded by a year’s worst flood, 1-in-1 to 1-in-10,000 years; diamonds = the five hazard scenarios; '
            f'grey band = {low:g}th–{high:g}th percentile of re-sampled years.',
            f'“1-in-100” ≈ 1% chance in any year. Right of the dashed line (1-in-{rarest:g}) only damage uncertainty varies.',
            ['PROXY', 'ASSUMPTION', *state.exposure_labels(report)], source=f'hazard tiers · assumed return periods · adapted JRC curves · {state.exposure_words(report)}')

with st.expander('Loss table', icon=':material/table:'):
    st.dataframe(pd.DataFrame([{'Rarity': f"1-in-{p['return_period_years']:,.0f}", 'Annual chance': f"{p['annual_exceedance_probability']:.2%}",
                                'Loss': state.kes(p['loss_kes'], compact=False),
                                f'Range ({low:g}–{high:g}th pct)': f"{state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])}",
                                'Modelled from': 'hazard tiers' if p['return_period_years'] <= rarest else 'damage uncertainty only'} for p in sim['table']]),
                 hide_index=True, width='stretch')
with st.expander('The five scenarios and their damage-uncertainty ranges', icon=':material/stacked_bar_chart:'):
    source = report['runs'][run] if basis == 'gross' else report['runs'][run]['insured']
    try: damage = state.uncertainty(report)[run]['insured' if basis == 'insured' else 'gross']
    except ModelError: damage = None
    st.dataframe(pd.DataFrame([{'Tier': p['tier'], 'Assumed rarity': state.rp_label(p['return_period_years']), 'Loss': state.kes(p['loss_kes'], compact=False),
                                '% of value': state.pct(p['loss_pct_of_tiv']),
                                **({'If damage curves are uncertain': f"{state.kes(damage['by_tier'][p['tier']]['p_low_kes'])} – {state.kes(damage['by_tier'][p['tier']]['p_high_kes'])}"} if damage else {})}
                               for p in source['ep_curve']]), hide_index=True, width='stretch')
    st.caption('Tier names describe how extreme a map cell is, not how often it floods: “extreme” is the most frequent event, “common” the rarest.')
if basis == 'insured':
    t = report['runs'][run]['insured']['terms']
    st.caption(f"Policy terms: deductible {t['deductible_pct_of_tiv']:.1%}, limit {t['limit_pct_of_tiv']:.0%} of value per property (or each row's own terms). Reinsurance not modelled.")

section('By construction')
tier, rp = tier_selector('results_tier')
b = report['runs'][run]['breakdowns'][tier]
rows = [{'Class': state.class_label(i['id']), 'Loss (KES m)': round(float(i['loss_kes'])/1e6, 1), 'Insured value': state.kes(i['tiv_kes']),
         'Properties': i['property_count'], '_label': f"{i['loss_share_pct']:.0f}% · {state.kes(i['loss_kes'])}"} for i in b['construction']]
chart = hbars(rows, 'Class', 'Loss (KES m)', 'Loss (KES m)', text='_label', height_per=40)
if chart: st.altair_chart(chart, width='stretch')

with st.container(border=True):
    section('Ask the results'); badges('AI')
    from ui.ask_view import ask_panel
    ask_panel(report, key='ask_results')
