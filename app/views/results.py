import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from ui import state
from ui.charts import class_bars, ep_chart
from ui.components import badges, page_header, require_result, run_banner, tier_selector

page_header('Loss curve', 'Exceedance-probability (EP) curve: the loss you should expect to be exceeded at each level of flood rarity.',
            ('PROXY', 'ASSUMPTION', 'SYNTHETIC'))
report = require_result()
run_banner(report)
cfg = state.config()
runs = ['baseline'] + (['enhanced'] if 'enhanced' in report['runs'] else [])
run = 'baseline'
if len(runs) > 1:
    run = st.segmented_control('Model', runs, default='baseline',
                               format_func={'baseline': 'Baseline', 'enhanced': 'With AI evidence'}.get) or 'baseline'

st.altair_chart(ep_chart(report, compare_ai=len(runs) > 1), width='stretch')
st.markdown('**How to read this:** a point at *1-in-100* means a loss at least that large has an assumed 1% chance of happening in any '
            'single year — not that it happens once a century.')

table = pd.DataFrame([{'Tier': p['tier'], 'Return period': state.rp_label(p['return_period_years']),
                       'Annual chance': f"{p['annual_exceedance_probability']:.1%}", 'Loss (KES)': state.kes(p['loss_kes'], compact=False),
                       '% of insured value': state.pct(p['loss_pct_of_tiv'])} for p in report['runs'][run]['ep_curve']])
st.dataframe(table, hide_index=True, width='stretch')

aal = report['runs'][run]['aal']
with st.container(border=True):
    st.markdown(f"**Average annual loss: {state.kes(aal['aal_kes'], compact=False)}**")
    st.caption(f"{aal['method']}. Zero loss assumed at {state.rp_label(aal['zero_loss_return_period_years'])}; the "
               f"{state.rp_label(max(cfg.return_periods.values()))} loss is held for rarer events, which contributes "
               f"{state.kes(aal['tail_contribution_kes'])}. ASSUMPTION — not a calibrated annual loss.")

st.subheader('Breakdown for one flood')
tier, rp = tier_selector('results_tier')
b = report['runs'][run]['breakdowns'][tier]
st.altair_chart(class_bars(b['construction']), width='stretch')
st.dataframe(pd.DataFrame([{'Class': state.class_label(i['id']), 'Properties': i['property_count'], 'Insured value': state.kes(i['tiv_kes']),
                            'Loss': state.kes(i['loss_kes']), 'Share of loss': f"{i['loss_share_pct']:.1f}%"} for i in b['construction']]),
             hide_index=True, width='stretch')
