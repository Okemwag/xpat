"""Sign in or register: the person says who they are (user or administrator) and what they want to do.

The forms themselves live on the auth server (FastAPI, /auth); this page only routes there with the right context.
"""

from urllib.parse import quote
import streamlit as st
from floodcat.platform.identity import app_url
from floodcat.platform.registration import signup_enabled
from ui import site, state
from ui.components import link

ROLES = {
    "user": {
        "label": "User",
        "who": "Underwriters, analysts, reviewers and viewers who work with portfolios and results.",
        "signin": "Sign in to your workspace",
        "new_title": "New to Xpat?",
        "new_text": "Ask to join your organisation using its code (your administrator has it). An administrator approves your account and decides what you can do.",
        "new_button": "Request an account",
        "register": "/auth/register?kind=join",
    },
    "admin": {
        "label": "Administrator",
        "who": "The person who manages an organisation: members, roles, security and settings.",
        "signin": "Sign in to administration",
        "new_title": "Setting up a new organisation?",
        "new_text": "Create the organisation. You become its administrator and can invite colleagues straight away.",
        "new_button": "Create an organisation",
        "register": "/auth/register?kind=org",
    },
}

site.css()
_, mid, _ = st.columns([1, 3, 1])
with mid:
    st.title("Sign in or create an account")
    st.caption("Choose how you use Xpat. You can switch at any time.")
    chosen = (
        st.segmented_control(
            "I am",
            list(ROLES),
            default=st.query_params.get("as", "user")
            if st.query_params.get("as") in ROLES
            else "user",
            format_func=lambda r: ROLES[r]["label"],
            key="signin_role",
        )
        or "user"
    )
    role = ROLES[chosen]
    st.caption(role["who"])

    have, new = st.columns(2, gap="medium")
    with have.container(border=True, height="stretch"):
        st.markdown("**I have an account**")
        st.write("Sign in with your work e-mail and password.")
        link(
            role["signin"],
            state.auth_link(
                f"/auth/login?as={chosen}&next={quote(app_url() + '/?as=' + chosen)}"
            ),
        )
        st.caption(f"[Forgot your password?]({state.auth_link('/auth/forgot')})")
    with new.container(border=True, height="stretch"):
        st.markdown(f"**{role['new_title']}**")
        if signup_enabled():
            st.write(role["new_text"])
            link(role["new_button"], state.auth_link(role["register"]), primary=False)
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
    st.caption(
        "Sign-ins and account changes are recorded in your organisation's audit log."
    )
site.footer()
