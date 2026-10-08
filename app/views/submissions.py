import pandas as pd
import streamlit as st
from floodcat.platform import data
from floodcat.underwriting.decision import OUTCOME_LABEL
from ui import state
from ui.charts import columns_chart
from ui.components import kpis, page_header, section, when

p = state.principal()
page_header('Submissions', 'Each cedant or broker submission, its analyses, its status and the decisions taken on it.')
STATUS_LABEL = {'received': 'Received', 'under_review': 'Under review', 'referred': 'Referred', 'quoted': 'Quoted', 'bound': 'Bound', 'declined': 'Declined'}
STATUS_COLOUR = {'received': 'gray', 'under_review': 'blue', 'referred': 'orange', 'quoted': 'violet', 'bound': 'green', 'declined': 'red'}
with state.platform().tx() as conn:
    subs = data.list_submissions(conn, p)
people = state.people()

if p.can('submissions.manage'):
    with st.expander('New submission', icon=':material/add:', expanded=not subs):
        with st.form('new_sub', clear_on_submit=True):
            name = st.text_input('Name', placeholder='e.g. Landmark Plaza — facultative flood')
            a, b, c = st.columns(3)
            cedant = a.text_input('Cedant / insured'); broker = b.text_input('Broker'); inception = c.text_input('Inception (YYYY-MM-DD)')
            if st.form_submit_button('Create', type='primary') and name:
                if state.guarded(data.create_submission, name, cedant, broker, inception) is not state.FAILED: st.rerun()
if not subs:
    st.info('No submissions yet.', icon=':material/work:'); st.stop()

counts = {s: sum(x['status'] == s for x in subs) for s in STATUS_LABEL}
kpis([('Submissions', len(subs)), ('Open', counts['received'] + counts['under_review'] + counts['referred'], 'Received, under review or referred'),
      ('Referred', counts['referred'], 'Waiting for the head of underwriting'), ('Quoted', counts['quoted']), ('Bound', counts['bound']),
      ('Assigned to you', sum(x['assignee_id'] == p.user_id for x in subs))])

left, right = st.columns([2, 3], gap='large')
with left.container(border=True, height='stretch'):
    section('Pipeline')
    chart = columns_chart([{'Status': STATUS_LABEL[s], 'Submissions': n} for s, n in counts.items()], 'Status', 'Submissions', 'Submissions', height=240,
                          sort=list(STATUS_LABEL.values()))
    st.altair_chart(chart, width='stretch', alt='Number of submissions at each status')
with right.container(border=True, height='stretch'):
    with st.container(horizontal=True, vertical_alignment='bottom'):
        status = st.pills('Status', list(STATUS_LABEL), selection_mode='multi', format_func=STATUS_LABEL.get, key='sub_status')
        mine = st.toggle('Only assigned to me', value=False)
    shown = [s for s in subs if (not mine or s['assignee_id'] == p.user_id) and (not status or s['status'] in status)]
    st.dataframe(pd.DataFrame([{'Name': s['name'], 'Cedant': s['cedant'], 'Broker': s['broker'], 'Status': STATUS_LABEL[s['status']],
                                'Assigned to': people.get(s['assignee_id'], '—'), 'Insured value': state.kes(s['tiv_kes']) if s['tiv_kes'] else '—',
                                'Rarest-scenario loss': state.kes(s['loss_250_kes']) if s['loss_250_kes'] else '—', 'Updated': when(s['updated_at'])}
                               for s in shown], columns=['Name', 'Cedant', 'Broker', 'Status', 'Assigned to', 'Insured value', 'Rarest-scenario loss', 'Updated']),
                 hide_index=True, width='stretch', height=260, alt='Submissions')
if not shown: st.caption('No submissions match these filters.'); st.stop()

choice = st.selectbox('Open a submission', [s['id'] for s in shown], format_func={s['id']: f"{s['name']} — {STATUS_LABEL[s['status']]}" for s in shown}.get)
sub = next(s for s in shown if s['id'] == choice)
with state.platform().tx() as conn:
    reasons = data.exceeds_authority(conn, p, sub)
    runs = data.list_runs(conn, p, submission_id=sub['id'])
    notes = data.list_comments(conn, p, 'submission', sub['id'])
    decided = data.list_decisions(conn, p, submission_id=sub['id'])
with st.container(border=True):
    head = st.container(horizontal=True, vertical_alignment='center')
    head.markdown(f"### {sub['name']}")
    head.badge(STATUS_LABEL[sub['status']], color=STATUS_COLOUR[sub['status']])
    st.caption(f"Cedant {sub['cedant'] or '—'} · broker {sub['broker'] or '—'} · inception {sub['inception'] or '—'} · assigned to {people.get(sub['assignee_id'], '—')} "
               f"· updated {when(sub['updated_at'])}")
    kpis([('Insured value', state.kes(sub['tiv_kes']) if sub['tiv_kes'] else '—', 'From the latest linked analysis'),
          ('Rarest-scenario loss', state.kes(sub['loss_250_kes']) if sub['loss_250_kes'] else '—'),
          ('Analyses', len(runs)), ('Decisions', len(decided), None, OUTCOME_LABEL[decided[0]['outcome']] if decided else None)])
    if reasons: st.warning('Above your organisation\'s authority limits: ' + '; '.join(reasons) + '. Quoting needs the head of underwriting.', icon=':material/gavel:')
    if sub['status'] == 'referred' and sub['referral_reason']: st.info(f"Referral reason: {sub['referral_reason']}", icon=':material/forward_to_inbox:')

    act_tab, runs_tab, dec_tab, notes_tab = st.tabs([':material/swap_horiz: Status & owner', f':material/analytics: Analyses ({len(runs)})',
                                                     f':material/gavel: Decisions ({len(decided)})', f':material/chat: Notes ({len(notes)})'])
    with act_tab:
        if p.can('submissions.manage'):
            a, b = st.columns(2, gap='large')
            with a:
                nxt = sorted(data.TRANSITIONS[sub['status']])
                if nxt:
                    target = st.selectbox('Move to', nxt, format_func=STATUS_LABEL.get)
                    note = st.text_input('Note (required for a referral)')
                    if st.button('Update status', type='primary'):
                        if state.guarded(data.move_submission, sub['id'], target, note) is not state.FAILED: st.rerun()
                else:
                    st.caption('Bound submissions are final.')
            with b:
                if people:
                    who = st.selectbox('Assign to', list(people), index=list(people).index(sub['assignee_id']) if sub['assignee_id'] in people else 0, format_func=people.get)
                    if st.button('Assign'):
                        if state.guarded(data.assign_submission, sub['id'], who) is not state.FAILED: st.rerun()
            if p.can('runs.create') and st.button('Work on this submission in the Portfolio', icon=':material/upload_file:'):
                st.session_state['active_submission'] = sub['id']; st.switch_page('views/portfolio.py')
        else:
            st.caption('Your role can follow submissions but not change them.')
    with runs_tab:
        if runs:
            st.dataframe(pd.DataFrame([{'Analysis': r['label'], 'When': when(r['created_at']), 'By': people.get(r['owner_id'], '—'),
                                        'Properties': r['summary']['modelled_count'], 'Insured value': state.kes(r['summary']['modelled_tiv_kes']),
                                        'Average annual loss': state.kes(r['summary']['aal_kes']), 'Data': ' + '.join(r['summary'].get('origin', []))} for r in runs]),
                         hide_index=True, width='stretch', alt='Analyses linked to this submission')
            st.caption('Open an analysis from Reports & history to see its results, decide on it or download its report.')
        else:
            st.caption('No analyses linked yet. Use “Work on this submission in the Portfolio” and run one.')
    with dec_tab:
        if decided:
            st.dataframe(pd.DataFrame([{'When': when(d['created_at']), 'Who': people.get(d['decided_by'], '—'), 'Premium (100%)': state.kes(d['premium_100_kes']),
                                        'Rules said': OUTCOME_LABEL[d['recommendation']['outcome']], 'Decision': OUTCOME_LABEL[d['outcome']]
                                        + (f" ({float(d['share_pct']):g}%)" if d['outcome'] == 'share' else ''),
                                        'Overrode rules': 'yes' if d['overrode'] else '', 'Reason': d['reason'] or ''} for d in decided]),
                         hide_index=True, width='stretch', alt='Underwriting decisions on this submission')
        else:
            st.caption('No decisions yet. Open a linked analysis and use the Underwriting decision page.')
    with notes_tab:
        for n in notes:
            with st.chat_message('user', avatar=':material/person:'):
                st.markdown(f"**{people.get(n['author_id'], 'Someone')}** · {when(n['created_at'])}  \n{n['body']}")
        if not notes: st.caption('No notes yet.')
        if p.can('comments.write'):
            with st.form('note', clear_on_submit=True):
                body = st.text_area('Add a note', placeholder='e.g. Broker confirmed the GPS point is the CBD site, not Upper Hill.')
                if st.form_submit_button('Add note') and body:
                    if state.guarded(data.add_comment, 'submission', sub['id'], body) is not state.FAILED: st.rerun()
