import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.services.accounts import ROLE_HELP
from ui import state

_, middle, _ = st.columns([1, 2, 1])
with middle:
    st.title('Welcome to Xpat')
    choice = st.segmented_control('Account', ['Sign in', 'Create account'], label_visibility='collapsed',
                                  default='Create account' if st.session_state.get('auth_tab') == 'register' else 'Sign in')
    if choice == 'Create account':
        with st.form('register', border=True):
            name = st.text_input('Your name', max_chars=80)
            organisation = st.text_input('Organisation (optional)', max_chars=120)
            username = st.text_input('Username', max_chars=32, help='3–32 characters: letters, digits, . _ -')
            password = st.text_input('Password', type='password', help='At least 10 characters with upper- and lower-case letters and a digit')
            confirm = st.text_input('Confirm password', type='password')
            st.caption(f"New accounts are analysts ({ROLE_HELP['analyst'].lower()}). An admin can grant the reviewer role.")
            submitted = st.form_submit_button('Create account', type='primary', width='stretch')
        if submitted:
            if password != confirm: st.error('The passwords do not match.')
            else:
                try:
                    record = state.accounts().register(username, password, name, organisation=organisation)
                    state.sign_in(record); st.rerun()
                except ModelError as exc: st.error(str(exc))
    else:
        with st.form('signin', border=True):
            username = st.text_input('Username')
            password = st.text_input('Password', type='password')
            submitted = st.form_submit_button('Sign in', type='primary', width='stretch')
        if submitted:
            try:
                state.sign_in(state.accounts().authenticate(username, password)); st.rerun()
            except ModelError as exc: st.error(str(exc))
    if state.guest_allowed():
        st.divider()
        st.write('Judging or just looking? Explore with a temporary guest session — no account needed.')
        if st.button('Continue as guest', icon=':material/visibility:', width='stretch'):
            state.sign_in_guest(); st.rerun()
    st.caption('Accounts are stored locally on this server for the prototype. Do not reuse a password from elsewhere.')
