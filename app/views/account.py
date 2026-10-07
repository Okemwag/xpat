import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.services.accounts import ROLE_HELP
from ui import state
from ui.components import page_header

user = state.user()
page_header('Account')
with st.container(border=True):
    st.markdown(f"**{user['display_name']}**" + (f" · {user['organisation']}" if user.get('organisation') else ''))
    st.markdown(f"Username `{user['username']}` · role **{user['role']}** — {ROLE_HELP.get(user['role'], '')}")
if user.get('guest'):
    st.info('This is a temporary guest session. Create an account to keep your runs under your own name.', icon=':material/info:')
else:
    st.subheader('Change password')
    with st.form('pw'):
        old = st.text_input('Current password', type='password')
        new = st.text_input('New password', type='password')
        confirm = st.text_input('Confirm new password', type='password')
        if st.form_submit_button('Update password'):
            if new != confirm: st.error('The new passwords do not match.')
            else:
                try: state.accounts().change_password(user['username'], old, new); st.success('Password updated.')
                except ModelError as exc: st.error(str(exc))
if st.button('Sign out', icon=':material/logout:'):
    state.sign_out(); st.rerun()
