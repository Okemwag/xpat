import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.services.accounts import ROLES, ROLE_HELP
from ui import state
from ui.components import page_header

if not state.is_admin():
    st.error('Admins only.'); st.stop()
page_header('Users', 'Grant the reviewer role to people who may approve AI-extracted evidence.')
users = state.accounts().list_users()
st.dataframe(pd.DataFrame(users), hide_index=True, width='stretch')
with st.form('role'):
    who = st.selectbox('User', [u['username'] for u in users])
    role = st.selectbox('Role', ROLES, format_func=lambda r: f'{r} — {ROLE_HELP[r]}')
    if st.form_submit_button('Set role', type='primary'):
        try: state.accounts().set_role(who, role, state.user()); st.success(f'{who} is now {role}.'); st.rerun()
        except ModelError as exc: st.error(str(exc))
