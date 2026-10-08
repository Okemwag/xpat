from datetime import datetime, time, timezone
import pandas as pd
import streamlit as st
from floodcat.platform import audit, identity
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Audit log', 'Every sign-in, administrative change and data action in your organisation. Append-only and tamper-evident.')
with state.platform().tx() as conn:
    people = {m['id']: f"{m['display_name']} ({m['email']})" for m in identity.list_members(conn, p)} if p.can('users.manage') or p.can('access_review.read') else {}
a, b, c, d = st.columns(4)
actor = a.selectbox('Person', [None]+list(people), format_func=lambda k: 'Anyone' if k is None else people[k])
action = b.selectbox('Action', [None, 'auth.', 'user.', 'run.', 'ai.', 'evidence.', 'assumptions.', 'submission.', 'org.', 'sso.', 'support.', 'api_token.', 'team.'],
                     format_func=lambda k: 'Any' if k is None else k.rstrip('.'))
since = c.date_input('From', value=None); until = d.date_input('To', value=None)
with state.platform().tx() as conn:
    events = audit.query(conn, p.org_id, actor_id=actor, action=action,
                         since=datetime.combine(since, time.min, timezone.utc) if since else None,
                         until=datetime.combine(until, time.max, timezone.utc) if until else None, limit=2000)
    total = audit.count(conn, p.org_id)
st.caption(f'{len(events):,} of {total:,} events shown (newest first).')
names = {**people}
frame = pd.DataFrame([{'When (UTC)': when(e['at'], '%Y-%m-%d %H:%M:%S'), 'Who': names.get(e['actor_id'], e['actor_id'] or 'system / anonymous'),
                       'Action': e['action'], 'Outcome': e['outcome'], 'Target': f"{e['target_type'] or ''} {e['target_id'] or ''}".strip(),
                       'From': e['ip'] or '', 'Details': str(e['details'])[:300]} for e in events])
st.dataframe(frame, hide_index=True, width='stretch', height=520)
x, y = st.columns(2)
x.download_button('Export (CSV)', frame.to_csv(index=False), 'xpat-audit-log.csv', 'text/csv', icon=':material/download:')
if y.button('Verify integrity', icon=':material/verified:'):
    with state.platform().tx() as conn: ok, bad = audit.verify_chain(conn)
    st.success('The audit chain is intact: no record has been altered or removed.') if ok else st.error(f'The audit chain is broken at record {bad}. Contact Xpat security.')
