"""Xpat — Nairobi flood risk. Run: uv run --extra ui --extra ai streamlit run app/streamlit_app.py"""
import os
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
# Read .env (KEY=VALUE lines) without overriding variables already set in the environment.
if (ROOT/'.env').exists():
    for line in (ROOT/'.env').read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key and not key.startswith('#') and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

from ui import state  # noqa: E402  (after .env so runtime settings apply)
st.set_page_config(page_title='Xpat · Nairobi flood risk', page_icon=str(ROOT/'logo.png'), layout='wide',
                   initial_sidebar_state='expanded')
st.logo(str(ROOT/'logo.png'), size='large')

public = [
    st.Page('views/landing.py', title='Welcome', icon=':material/home:', default=True),
    st.Page('views/auth.py', title='Sign in', icon=':material/login:'),
    st.Page('views/method.py', title='How the model works', icon=':material/menu_book:'),
]

user = state.user()
if user is None:
    nav = st.navigation(public, position='top')
else:
    workspace = [st.Page('views/overview.py', title='Overview', icon=':material/dashboard:', default=True),
                 st.Page('views/portfolio.py', title='Portfolio', icon=':material/upload_file:')]
    results = [st.Page('views/results.py', title='Loss curve', icon=':material/show_chart:'),
               st.Page('views/map.py', title='Accumulation map', icon=':material/map:'),
               st.Page('views/property.py', title='Property explorer', icon=':material/home_work:')]
    model = [st.Page('views/assumptions.py', title='Assumptions & sensitivity', icon=':material/tune:'),
             st.Page('views/evidence.py', title='AI flood evidence', icon=':material/auto_awesome:'),
             st.Page('views/honesty.py', title='Data & honesty', icon=':material/verified:'),
             st.Page('views/method.py', title='How the model works', icon=':material/menu_book:')]
    account = [st.Page('views/history.py', title='Reports & history', icon=':material/history:'),
               st.Page('views/account.py', title='Account', icon=':material/person:')]
    if state.is_admin(): account.append(st.Page('views/admin.py', title='Users', icon=':material/admin_panel_settings:'))
    nav = st.navigation({'Workspace': workspace, 'Results': results, 'Model': model, 'Account': account})
    with st.sidebar:
        with st.container(border=True):
            st.markdown(f"**{user['display_name']}**  \n{user['role'].title()}" + (' · guest session' if user.get('guest') else ''))
            if st.button('Sign out', icon=':material/logout:', width='stretch'):
                state.sign_out(); st.rerun()
        if state.result():
            st.caption(f"Current run: {st.session_state.get('run_label', '—')}")
        st.caption('AI features: ' + ('available (Gemini)' if state.ai_available() else 'off — set GEMINI_API_KEY'))
        st.caption('All results are illustrative: synthetic portfolio, proxy hazard, assumed return periods.')
nav.run()
