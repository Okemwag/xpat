import streamlit as st
from floodcat.platform import identity, security
from ui import state
from ui.components import link

p = state.principal()
st.title("Set up two-step verification")
st.write(
    f"**{state.org().get('name', 'Your organisation')}** requires two-step verification for your role. It takes a minute: you need an "
    "authenticator app on your phone (Microsoft Authenticator, Google Authenticator, 1Password, Authy…)."
)
if "mfa_secret" not in st.session_state:
    with state.platform().tx() as conn:
        st.session_state["mfa_secret"], st.session_state["mfa_uri"] = (
            identity.begin_mfa(conn, p)
        )
left, right = st.columns([1, 2], gap="large")
with left:
    st.html(security.qr_svg(st.session_state["mfa_uri"]))
with right:
    st.markdown("**1.** Scan the code with your authenticator app.")
    st.caption(
        f"Can't scan? Enter this key instead: `{st.session_state['mfa_secret']}`"
    )
    st.markdown("**2.** Enter the 6-digit code it shows.")
    code = st.text_input("Code", max_chars=8, key="mfa_code")
    if st.button("Turn on two-step verification", type="primary"):
        try:
            with state.platform().tx() as conn:
                codes = identity.confirm_mfa(conn, p, code, state.request_info())
            st.session_state["recovery_codes"] = codes
            st.session_state.pop("mfa_secret")
            st.session_state.pop("mfa_uri")
        except Exception as exc:
            st.error(str(exc))
if st.session_state.get("recovery_codes"):
    st.success("Two-step verification is on.")
    st.markdown(
        "**Save these recovery codes now.** Each works once if you lose your phone. They will not be shown again."
    )
    st.code("\n".join(st.session_state["recovery_codes"]))
    st.download_button(
        "Download recovery codes",
        "\n".join(st.session_state["recovery_codes"]),
        "xpat-recovery-codes.txt",
    )
    if st.button("I have saved them — continue", type="primary"):
        st.session_state.pop("recovery_codes")
        st.rerun()
st.divider()
link("Sign out", state.auth_link("/auth/logout"), primary=False)
