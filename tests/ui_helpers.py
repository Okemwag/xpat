"""Create a real organisation, user and session for interface tests (no cookies in AppTest, so the token goes in session state)."""

PW = "a long and unusual passphrase 42"


def make_session(
    store_dir, roles=("underwriter",), org_name="Test Re", email="tester@test.re"
):
    import os

    os.environ["FLOODCAT_BREACH_CHECK"] = "0"
    from sqlalchemy import select
    from floodcat.platform import identity
    from floodcat.platform.db import users
    from floodcat.platform.email import recent
    from floodcat.platform.service import Platform

    plat = Platform(f"sqlite:///{store_dir}/platform.db")
    with plat.tx() as c:
        org_id, raw_invite = identity.create_organisation(
            c, None, org_name, email, settings={"mfa_policy": "off"}
        )
        user_id, _ = identity.accept_invitation(
            c, raw_invite, display_name="Tester", password=PW
        )
        c.execute(
            identity.memberships.update()
            .where(identity.memberships.c.user_id == user_id)
            .values(roles=list(roles))
        )
        raw, _ = identity.start_session(c, user_id, org_id)
    return raw


def page_preamble(store_dir, token):
    """Code each AppTest script runs before exec-ing a page."""
    import os

    os.environ["FLOODCAT_STORE_DIR"] = store_dir
    os.environ["FLOODCAT_DATABASE_URL"] = f"sqlite:///{store_dir}/platform.db"
    import streamlit as st
    from ui import state

    state.platform.clear()
    st.session_state["_test_session_token"] = token
    state.resolve()
