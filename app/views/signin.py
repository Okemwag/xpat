import streamlit as st
from floodcat.platform.identity import app_url
from ui import site, state
from ui.components import link

site.css()
_, mid, _ = st.columns([1, 2, 1])
with mid:
    site.hero('Sign in', 'Welcome back to <span class="x-accent">Xpat</span>',
              'Sign in with your work account. Access is by invitation from your organisation\'s administrator.')
    st.space('small')
    with st.container(border=True):
        st.markdown('**Your organisation uses Microsoft, Google or another company sign-in?**')
        link('Sign in with your company (SSO)', state.auth_link(f'/auth/sso?next={app_url()}'), icon='🏢')
        st.space('small')
        st.markdown('**Or use your Xpat password**')
        link('Sign in with e-mail and password', state.auth_link(f'/auth/login?next={app_url()}'), primary=False, icon='🔑')
        st.caption(f"[Forgot your password?]({state.auth_link('/auth/forgot')})")
    if state.guest_allowed():
        with st.container(border=True):
            st.markdown('**Judging or just looking?** Try the public demo — a temporary, separate workspace with the sample portfolio.')
            link('Explore the demo', state.auth_link('/auth/guest'), primary=False, icon='👀')
    st.caption('New to Xpat? Ask your administrator for an invitation, or contact us to set up your organisation.')
    st.caption('All sign-ins and account changes are recorded in your organisation\'s audit log.')
site.footer()
