import json
import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.reporting.export import json_report, property_csv
from floodcat.reporting.summary import markdown_summary
from ui import state
from ui.components import page_header

page_header('Reports & history', 'Download the current results, or reopen an earlier run.')
report = state.result()
if report:
    st.subheader('Current run')
    cfg = state.config()
    c = st.container(horizontal=True)
    c.download_button('Summary (Markdown)', markdown_summary(report), 'xpat_summary.md', 'text/markdown', icon=':material/description:')
    c.download_button('Full report (JSON)', json_report(report), 'xpat_report.json', 'application/json', icon=':material/data_object:')
    tier = st.selectbox('Property losses for', TIERS, index=len(TIERS)-1, format_func=lambda t: f'{state.rp_label(cfg.return_periods[t])} ({t})')
    runs = list(report['runs'])
    for run in runs:
        c.download_button(f"Property losses CSV ({'AI' if run == 'enhanced' else 'baseline'})", property_csv(report, run, tier),
                          f'xpat_property_losses_{run}_{tier}.csv', 'text/csv', icon=':material/table:', key=f'csv_{run}')

st.subheader('Your saved runs')
store = state.runtime().store
try:
    runs = store.list_analyses(owner=state.user()['username']) if hasattr(store, 'delete_analysis') else store.list_analyses()
except ModelError as exc:
    st.error(str(exc)); runs = []
if not runs:
    st.info('No saved runs yet. Every analysis you run is saved here automatically.')
for r in runs:
    with st.container(border=True, horizontal=True, vertical_alignment='center'):
        st.markdown(f"**{r.get('label', 'Run')}**  \n{r['created_at'][:16].replace('T', ' ')} UTC · {r['modelled_count']} properties · "
                    f"{state.kes(r.get('modelled_tiv_kes', 0))} insured · AAL {state.kes(r.get('aal_kes', 0))}" + (' · AI' if r.get('ai_enabled') else ''))
        if st.button('Open', key=f"open_{r['analysis_id']}"):
            loaded = store.get_analysis(r['analysis_id'])
            state.set_result(loaded, [], r.get('label', 'Saved run'))
            st.session_state['config_overrides'] = {}
            st.toast('Opened. Re-running with new assumptions needs the original file.')
            st.switch_page('views/overview.py')
        if hasattr(store, 'delete_analysis') and st.button('Delete', key=f"del_{r['analysis_id']}", icon=':material/delete:'):
            store.delete_analysis(r['analysis_id'], state.user()['username']); st.rerun()
