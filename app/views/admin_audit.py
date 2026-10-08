from collections import Counter
from datetime import datetime, time, timezone
import pandas as pd
import streamlit as st
from floodcat.platform import audit, identity
from ui import state
from ui.charts import hbars, timeline
from ui.components import kpis, page_header, section, when

p = state.principal()
page_header('Audit log', 'Every sign-in, administrative change and data action in your organisation. Append-only and tamper-evident.')
with state.platform().tx() as conn:
    people = {m['id']: f"{m['display_name']} ({m['email']})" for m in identity.list_members(conn, p)} if p.can('users.manage') or p.can('access_review.read') else {}
AREAS = [None, 'auth.', 'user.', 'run.', 'ai.', 'evidence.', 'assumptions.', 'underwriting.', 'submission.', 'org.', 'sso.', 'support.', 'api_token.', 'team.']
with st.container(border=True):
    a, b, c, d = st.columns(4)
    actor = a.selectbox('Person', [None]+list(people), format_func=lambda k: 'Anyone' if k is None else people[k])
    action = b.selectbox('Action', AREAS, format_func=lambda k: 'Any' if k is None else k.rstrip('.').replace('_', ' '))
    since = c.date_input('From', value=None); until = d.date_input('To', value=None)
with state.platform().tx() as conn:
    events = audit.query(conn, p.org_id, actor_id=actor, action=action,
                         since=datetime.combine(since, time.min, timezone.utc) if since else None,
                         until=datetime.combine(until, time.max, timezone.utc) if until else None, limit=2000)
    total = audit.count(conn, p.org_id)
problems = [e for e in events if e['outcome'] in ('denied', 'error', 'failure', 'failed')]
kpis([('Events shown', f'{len(events):,}', 'Newest first, up to 2,000'), ('All events', f'{total:,}', 'Since the organisation was created'),
      ('Denied or failed', f'{len(problems):,}', 'Wrong passwords, refused permissions, failed checks'),
      ('People involved', len({e['actor_id'] for e in events if e['actor_id']}))])
if events:
    left, right = st.columns([3, 2], gap='large')
    with left.container(border=True, height='stretch'):
        section('Activity per day')
        per_day = Counter(when(e['at'], '%Y-%m-%d') for e in events)
        chart = timeline([{'Day': d, 'Events': n} for d, n in sorted(per_day.items())], 'Day', 'Events', 'Events', height=200)
        if chart: st.altair_chart(chart, width='stretch', alt='Audit events per day')
    with right.container(border=True, height='stretch'):
        section('Most frequent actions')
        chart = hbars([{'Action': k, 'Events': n, '_label': f'{n:,}'} for k, n in Counter(e['action'] for e in events).most_common(8)],
                      'Action', 'Events', 'Events', text='_label', height_per=24)
        if chart: st.altair_chart(chart, width='stretch', alt='Most frequent audit actions')
names = {**people}
frame = pd.DataFrame([{'When (UTC)': when(e['at'], '%Y-%m-%d %H:%M:%S'), 'Who': names.get(e['actor_id'], e['actor_id'] or 'system / anonymous'),
                       'Action': e['action'], 'Outcome': e['outcome'], 'Target': f"{e['target_type'] or ''} {e['target_id'] or ''}".strip(),
                       'From': e['ip'] or '', 'Details': str(e['details'])[:300]} for e in events],
                     columns=['When (UTC)', 'Who', 'Action', 'Outcome', 'Target', 'From', 'Details'])
st.dataframe(frame, hide_index=True, width='stretch', height=480, alt='Audit events',
             column_config={'Details': st.column_config.TextColumn(width='large')})
with st.container(horizontal=True):
    st.download_button('Export (CSV)', frame.to_csv(index=False), 'xpat-audit-log.csv', 'text/csv', icon=':material/download:')
    if st.button('Verify integrity', icon=':material/verified:'):
        with state.platform().tx() as conn: ok, bad = audit.verify_chain(conn)
        st.success('The audit chain is intact: no record has been altered or removed.') if ok else st.error(f'The audit chain is broken at record {bad}. Contact Xpat security.')
