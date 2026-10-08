import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.platform import data
from floodcat.reporting.export import json_report, property_csv
from floodcat.reporting.summary import markdown_summary
from floodcat.core.errors import ModelError
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Reports & history', 'Download the current results, or reopen an analysis you or your colleagues have shared.')

def audited(fmt):
    report = state.result()
    if report: state.guarded(data.record_export, report['analysis_id'], fmt)

report = state.result()
if report:
    st.subheader('Current analysis')
    cfg = state.config()
    if not p.can('runs.export'):
        st.info('Your role cannot export results.')
    else:
        c = st.container(horizontal=True)
        try: ranges, ylt = state.uncertainty(report), state.ylt(report)
        except ModelError: ranges = ylt = None
        summary = markdown_summary(report, ranges, ylt)
        if state.current_briefing():
            from floodcat.ai.briefing import to_markdown
            summary += '\n---\n\n' + to_markdown(state.current_briefing()['briefing'])
        c.download_button('Summary (Markdown)', summary, 'xpat_summary.md', 'text/markdown', icon=':material/description:',
                          on_click=audited, args=('markdown',))
        c.download_button('Full report (JSON)', json_report(report), 'xpat_report.json', 'application/json', icon=':material/data_object:',
                          on_click=audited, args=('json',))
        tier = st.selectbox('Property losses for', TIERS, index=len(TIERS)-1, format_func=lambda t: f'{state.rp_label(cfg.return_periods[t])} ({t})')
        for run in report['runs']:
            c.download_button(f"Property losses CSV ({'AI' if run == 'enhanced' else 'baseline'})", property_csv(report, run, tier),
                              f'xpat_property_losses_{run}_{tier}.csv', 'text/csv', icon=':material/table:', key=f'csv_{run}', on_click=audited, args=('csv',))
        st.caption('Downloads are recorded in your organisation\'s audit log.')

st.subheader('Analyses you can see')
mine = st.toggle('Only mine', value=False)
with state.platform().tx() as conn:
    runs = data.list_runs(conn, p, mine_only=mine)
    from floodcat.platform.orgs import list_teams
    teams = {t['id']: t['name'] for t in list_teams(conn, p.org_id)}
if not runs: st.info('No analyses yet. Every analysis you run is saved here automatically.')
VIS = {'private': 'only me', 'team': 'my team', 'org': 'whole organisation'}
for r in runs:
    s = r['summary']
    with st.container(border=True):
        top = st.container(horizontal=True, vertical_alignment='center')
        top.markdown(f"**{r['label']}**  \n{when(r['created_at'])} · {s['modelled_count']} properties · {state.kes(s['modelled_tiv_kes'])} insured · "
                     f"AAL {state.kes(s['aal_kes'])} · {' + '.join(s.get('origin', []))}" + (' · AI' if s.get('ai_enabled') else '')
                     + f" · visible to {VIS[r['visibility']]}" + (f" ({teams.get(r['team_id'], 'team')})" if r['visibility'] == 'team' else ''))
        if top.button('Open', key=f"open_{r['id']}"):
            try:
                with state.platform().tx() as conn: run = data.get_run(conn, p, r['id'], with_inputs=p.can('runs.create'), request=state.request_info())
                state.set_result(run['payload'], run.get('inputs', []), r['label'], run['settings'])
                st.session_state['config_overrides'] = {}
                st.switch_page('views/overview.py')
            except ModelError as exc:
                st.error(str(exc))
        if r['owner_id'] == p.user_id:
            vis = top.selectbox('Share with', list(VIS), index=list(VIS).index(r['visibility']), format_func=VIS.get, key=f"vis_{r['id']}",
                                label_visibility='collapsed')
            if vis != r['visibility'] and state.guarded(data.set_visibility, r['id'], vis, p.team_ids[0] if vis == 'team' and p.team_ids else None) is not state.FAILED:
                st.rerun()
        if (r['owner_id'] == p.user_id or p.can('runs.delete_any')) and top.button('Delete', key=f"del_{r['id']}", icon=':material/delete:'):
            if state.guarded(data.delete_run, r['id']) is not state.FAILED: st.rerun()
