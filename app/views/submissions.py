import pandas as pd
import streamlit as st
from floodcat.platform import data, identity
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Submissions', 'Each cedant or broker submission, its analyses, its status and the decisions taken on it.')
STATUS_LABEL = {'received': 'Received', 'under_review': 'Under review', 'referred': 'Referred', 'quoted': 'Quoted', 'bound': 'Bound', 'declined': 'Declined'}
with state.platform().tx() as conn:
    subs = data.list_submissions(conn, p)
    people = {m['id']: m['display_name'] for m in identity.list_members(conn, p)} if (p.can('users.manage') or p.can('access_review.read')) else {}
    if not people:
        from sqlalchemy import select
        from floodcat.platform.db import memberships, users
        people = {r.id: r.display_name for r in conn.execute(select(users.c.id, users.c.display_name).join(memberships, memberships.c.user_id == users.c.id)
                                                             .where(memberships.c.org_id == p.org_id, memberships.c.status == 'active'))}
if p.can('submissions.manage'):
    with st.expander('New submission', icon=':material/add:'):
        with st.form('new_sub', clear_on_submit=True):
            name = st.text_input('Name', placeholder='e.g. Landmark Plaza — facultative flood')
            a, b, c = st.columns(3)
            cedant = a.text_input('Cedant / insured'); broker = b.text_input('Broker'); inception = c.text_input('Inception (YYYY-MM-DD)')
            if st.form_submit_button('Create', type='primary') and name:
                if state.guarded(data.create_submission, name, cedant, broker, inception) is not state.FAILED: st.rerun()
mine = st.toggle('Only submissions assigned to me', value=False)
shown = [s for s in subs if not mine or s['assignee_id'] == p.user_id]
st.dataframe(pd.DataFrame([{'Name': s['name'], 'Cedant': s['cedant'], 'Broker': s['broker'], 'Status': STATUS_LABEL[s['status']],
                            'Assigned to': people.get(s['assignee_id'], '—'), 'Insured value': state.kes(s['tiv_kes']) if s['tiv_kes'] else '—',
                            'Rarest-scenario loss': state.kes(s['loss_250_kes']) if s['loss_250_kes'] else '—', 'Updated': when(s['updated_at'])}
                           for s in shown]), hide_index=True, width='stretch')
if not shown: st.info('No submissions yet.'); st.stop()
choice = st.selectbox('Open a submission', [s['id'] for s in shown], format_func={s['id']: s['name'] for s in shown}.get)
sub = next(s for s in shown if s['id'] == choice)
with state.platform().tx() as conn:
    reasons = data.exceeds_authority(conn, p, sub)
    runs = data.list_runs(conn, p, submission_id=sub['id'])
    notes = data.list_comments(conn, p, 'submission', sub['id'])
with st.container(border=True):
    st.subheader(sub['name'])
    st.markdown(f"**{STATUS_LABEL[sub['status']]}** · assigned to {people.get(sub['assignee_id'], '—')} · cedant {sub['cedant'] or '—'} · broker {sub['broker'] or '—'}")
    if reasons: st.warning('Above your organisation\'s authority limits: ' + '; '.join(reasons) + '. Quoting needs the head of underwriting.', icon=':material/gavel:')
    if sub['status'] == 'referred' and sub['referral_reason']: st.info(f"Referral reason: {sub['referral_reason']}", icon=':material/forward_to_inbox:')
    if p.can('submissions.manage'):
        a, b = st.columns(2)
        with a:
            nxt = sorted(data.TRANSITIONS[sub['status']])
            if nxt:
                target = st.selectbox('Move to', nxt, format_func=STATUS_LABEL.get)
                note = st.text_input('Note (required for a referral)')
                if st.button('Update status', type='primary'):
                    if state.guarded(data.move_submission, sub['id'], target, note) is not state.FAILED: st.rerun()
        with b:
            who = st.selectbox('Assign to', list(people), index=list(people).index(sub['assignee_id']) if sub['assignee_id'] in people else 0, format_func=people.get)
            if st.button('Assign'):
                if state.guarded(data.assign_submission, sub['id'], who) is not state.FAILED: st.rerun()
        if p.can('runs.create') and st.button('Work on this submission in the Portfolio', icon=':material/upload_file:'):
            st.session_state['active_submission'] = sub['id']; st.switch_page('views/portfolio.py')
st.subheader('Analyses')
for r in runs:
    st.markdown(f"- **{r['label']}** · {when(r['created_at'])} · {r['summary']['modelled_count']} properties · AAL {state.kes(r['summary']['aal_kes'])}")
if not runs: st.caption('No analyses linked yet. Use "Work on this submission" and run one.')
st.subheader('Notes')
for n in notes: st.markdown(f"**{people.get(n['author_id'], 'Someone')}** · {when(n['created_at'])}  \n{n['body']}")
if p.can('comments.write'):
    with st.form('note', clear_on_submit=True):
        body = st.text_area('Add a note', placeholder='e.g. Broker confirmed the GPS point is the CBD site, not Upper Hill.')
        if st.form_submit_button('Add note') and body:
            if state.guarded(data.add_comment, 'submission', sub['id'], body) is not state.FAILED: st.rerun()
