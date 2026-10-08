import pandas as pd
import streamlit as st
from floodcat.platform import identity, orgs
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Organisations', 'Xpat staff only. You cannot see customer data unless a customer grants support access.')
with state.platform().tx() as conn: rows = orgs.list_orgs(conn, p)
st.dataframe(pd.DataFrame([{'Name': r['name'], 'Status': r['status'], 'Plan': r['plan'], 'Seats': r['seats'], 'Members': r['members'],
                            'Created': when(r['created_at'])} for r in rows]), hide_index=True, width='stretch')
with st.expander('Create an organisation', icon=':material/add_business:'):
    with st.form('new_org'):
        name = st.text_input('Organisation name'); owner = st.text_input('First owner\'s e-mail')
        domains = st.text_input('Allowed e-mail domains (comma-separated)')
        a, b = st.columns(2); plan = a.text_input('Plan', 'pilot'); seats = b.number_input('Seats', 1, 10000, 10)
        if st.form_submit_button('Create and invite owner', type='primary'):
            res = state.guarded(lambda conn, pr, request=None: identity.create_organisation(conn, pr, name, owner, plan=plan, seats=int(seats),
                                settings={'allowed_domains': [d.strip() for d in domains.split(',') if d.strip()]}, request=request))
            if res is not state.FAILED: st.success(f'Created. Invitation sent to {owner}.')
if rows:
    st.subheader('Manage')
    choice = st.selectbox('Organisation', [r['id'] for r in rows], format_func={r['id']: r['name'] for r in rows}.get)
    r = next(x for x in rows if x['id'] == choice)
    a, b = st.columns(2)
    with a:
        status = st.selectbox('Status', ['trial', 'active', 'suspended', 'closed'], index=['trial', 'active', 'suspended', 'closed'].index(r['status']),
                              help='Suspended = read-only. Closed = 30-day export window, then data is deleted by the retention job.')
        if st.button('Apply status'):
            if state.guarded(orgs.set_org_status, choice, status) is not state.FAILED: st.rerun()
    with b:
        plan = st.text_input('Plan', r['plan'], key='plan'); seats = st.number_input('Seats', 1, 10000, int(r['seats']), key='seats')
        if st.button('Apply plan'):
            if state.guarded(orgs.set_plan, choice, plan, int(seats)) is not state.FAILED: st.rerun()
    st.markdown('**Feature flags**')
    with state.platform().tx() as conn: flags = {f: orgs.flag_enabled(conn, choice, f) for f in orgs.FLAGS}
    cols = st.columns(len(orgs.FLAGS))
    for col, (flag, on) in zip(cols, flags.items()):
        new = col.toggle(flag.replace('_', ' '), value=on, key=f'flag_{flag}')
        if new != on and state.guarded(orgs.set_flag, choice, flag, new) is not state.FAILED: st.rerun()
