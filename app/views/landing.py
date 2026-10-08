import os
import streamlit as st
from ui import site, state
from ui.components import link

site.css()
CONTACT = os.getenv("FLOODCAT_CONTACT_EMAIL", "").strip()


@st.cache_data(show_spinner=False)
def sample_headline():
    report = state.runtime().run(state.runtime().sample_rows())
    curve = {
        p["return_period_years"]: p for p in report["runs"]["baseline"]["ep_curve"]
    }
    return {
        "tiv": report["modelled_tiv_kes"],
        "rp100": curve[100.0]["loss_kes"],
        "aal": report["runs"]["baseline"]["aal"]["aal_kes"],
    }


def actions(key):
    cols = st.columns([1, 1.3, 1, 1, 2])
    with cols[0]:
        if st.button(
            "Sign in", type="primary", icon=":material/login:", key=f"{key}_signin"
        ):
            st.switch_page("views/signin.py")
    with cols[1]:
        if st.button(
            "Create an account", icon=":material/person_add:", key=f"{key}_register"
        ):
            st.switch_page("views/signin.py")
    if CONTACT:
        with cols[2]:
            link(
                "Request a pilot",
                f"mailto:{CONTACT}?subject=Xpat%20pilot",
                primary=False,
            )
    if state.guest_allowed():
        with cols[3]:
            link("View demo", state.auth_link("/auth/guest"), primary=False)


# Hero
left, right = st.columns([3, 2], gap="large", vertical_alignment="center")
with left:
    site.hero(
        "For insurers and reinsurers",
        "Flood loss, property by property",
        "Upload a schedule or broker submission. Get the loss curve, the concentrations and the assumptions behind them.",
    )
    st.space("small")
    actions("hero")
with right:
    with st.container(border=True):
        st.caption("SAMPLE PORTFOLIO · NAIROBI · SYNTHETIC")
        try:
            h = sample_headline()
            st.metric("Insured value", state.kes(h["tiv"]))
            a, b = st.columns(2)
            a.metric("1-in-100 loss", state.kes(h["rp100"]))
            b.metric("Annual average", state.kes(h["aal"]))
        except Exception:
            st.caption("Preview unavailable.")

# Capabilities
site.section("Platform", "One model, from submission to decision")
site.cards(
    [
        (
            "",
            "Read any submission",
            "Schedules, PDFs and Word documents, checked before they are modelled.",
            (),
        ),
        (
            "",
            "Loss at every return period",
            "1-in-10 to 1-in-10,000 years, with average annual loss and ranges.",
            (),
        ),
        (
            "",
            "See accumulation",
            "Value and loss by location, area and construction.",
            (),
        ),
    ]
)

# How it works
site.section("How it works", "From schedule to decision in four steps")
site.cards(
    [
        ("1", "Upload", "Schedule or document.", ()),
        ("2", "Locate", "Flood hazard at each property.", ()),
        ("3", "Damage", "Published curves by construction type.", ()),
        ("4", "Decide", "Loss curve, review, refer, quote.", ()),
    ],
    columns=4,
)

# For organisations
site.section("For organisations", "Built for underwriting teams")
site.cards(
    [
        (
            "",
            "Secure by default",
            "Company sign-in (SSO), two-step verification, encrypted data.",
            (),
        ),
        (
            "",
            "Roles and approvals",
            "Underwriters, reviewers and approvers, with authority limits.",
            (),
        ),
        ("", "Full audit trail", "Every sign-in, change and export recorded.", ()),
    ]
)

# Assistant
site.section("Questions", "Ask the Xpat assistant")
_, chat_col, _ = st.columns([1, 6, 1])
with chat_col:
    from ui.chat_view import chat_panel

    chat_panel("home_assistant")
    st.caption(
        "Answers come from Xpat's own documentation, with sources. It cannot see any organisation's data."
    )

site.band("See your flood exposure", "Start with a pilot on your own portfolio.")
st.space("small")
_, mid, _ = st.columns([1, 2, 1])
with mid:
    actions("footer")
site.footer()
