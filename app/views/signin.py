"""Sign in or create an account. Creating one goes straight to the dashboard; the demo panel appears when enabled.

The forms themselves live on the auth server (FastAPI, /auth); this page only routes there with the right context.
"""

from urllib.parse import quote
import streamlit as st
from floodcat.platform.identity import app_url
from floodcat.platform.registration import signup_enabled
from ui import site, state
from ui.components import link

site.css()
_, mid, _ = st.columns([1, 3, 1])
with mid:
    st.title("Sign in or create an account")
    have, new = st.columns(2, gap="medium")
    with have.container(border=True, height="stretch"):
        st.markdown("**I have an account**")
        st.write("Sign in with your e-mail and password.")
        link("Sign in", state.auth_link(f"/auth/login?next={quote(app_url())}"))
        st.caption(f"[Forgot your password?]({state.auth_link('/auth/forgot')})")
    with new.container(border=True, height="stretch"):
        st.markdown("**New to Xpat?**")
        if signup_enabled():
            st.write("Create an account and go straight to your dashboard.")
            link("Create an account", state.auth_link("/auth/register"), primary=False)
        else:
            st.write(
                "Accounts on this server are by invitation. Ask your organisation's administrator to invite you."
            )

    st.space("small")
    other = st.container(horizontal=True, gap="medium")
    other.markdown(
        f"Company sign-in: [use your Microsoft or Google work account]({state.auth_link(f'/auth/sso?next={app_url()}')})"
    )
    if state.guest_allowed():
        other.markdown(
            f"Just looking: [open the public demo]({state.auth_link('/auth/guest')})"
        )
    from floodcat.platform import demo

    if demo.logins_enabled():
        with st.container(border=True):
            st.markdown(f"**Demo accounts** · {demo.DEMO_ORG}")
            st.caption(
                "One click signs in as each role in the demonstration organisation (synthetic data only). "
                "Turned on with FLOODCAT_DEMO_LOGINS=1; never available in production."
            )
            roles = [r for r, _ in demo.ACCOUNTS]
            for row in (roles[:4], roles[4:]):
                cols = st.columns(4)
                for col, r in zip(cols, row):
                    with col:
                        link(demo.ROLE_LABELS[r], state.auth_link(f"/auth/demo/{r}"), primary=r == "underwriter")
    st.caption(
        "Sign-ins and account changes are recorded in your organisation's audit log."
    )
site.footer()
