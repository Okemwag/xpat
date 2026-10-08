"""Self-service registration: a new organisation with the registrant as administrator, or a request to join that an
administrator approves. Confirmed by e-mail first; never a way to become an administrator of someone else's organisation."""

import re
import pytest
from sqlalchemy import select
from floodcat.core.errors import ModelError
from floodcat.platform import identity, registration
from floodcat.platform.db import audit_events, memberships, users
from floodcat.platform.email import recent
from floodcat.platform.service import Platform
from test_web_auth import PW, csrf, env  # noqa: F401  (fixture)

REQ = {"ip": "10.0.0.9", "user_agent": "pytest"}


@pytest.fixture
def plat(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOODCAT_BREACH_CHECK", "0")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("FLOODCAT_ALLOW_SIGNUP", raising=False)
    monkeypatch.setenv("FLOODCAT_STORE_DIR", str(tmp_path))
    return Platform(f"sqlite:///{tmp_path}/platform.db")


def link(plat, to, kind="signup_confirm"):
    with plat.tx() as c:
        msg = next(m for m in recent(c, to) if m["kind"] == kind)
    return re.search(r"/auth/register/confirm/(\S+)", msg["text"]).group(1)


def org_with_domain(plat, domain="join.re"):
    with plat.tx() as c:
        org_id, raw = identity.create_organisation(
            c, None, "Join Re", f"boss@{domain}", settings={"allowed_domains": [domain]}
        )
        user_id, _ = identity.accept_invitation(
            c, raw, display_name="Boss", password=PW
        )
        raw_s, _ = identity.start_session(c, user_id, org_id)
        admin, _ = identity.resolve_session(c, raw_s)
    return org_id, admin


def test_new_organisation_makes_the_registrant_its_administrator(plat):
    with plat.tx() as c:
        registration.start(
            c, "org", "founder@newco.re", "Fay Founder", PW, "NewCo Re", request=REQ
        )
        user = (
            c.execute(select(users).where(users.c.email == "founder@newco.re"))
            .mappings()
            .first()
        )
        assert user["status"] == "unverified"
        with pytest.raises(ModelError):
            identity.authenticate(
                c, "founder@newco.re", PW, REQ
            )  # cannot sign in before confirming
    with plat.tx() as c:
        result = registration.confirm(c, link(plat, "founder@newco.re"), REQ)
        roles = c.execute(
            select(memberships.c.roles).where(memberships.c.org_id == result["org_id"])
        ).scalar()
        settings = identity.settings_for(c, result["org_id"])
        assert (
            identity.authenticate(c, "founder@newco.re", PW, REQ)["status"] == "active"
        )
    assert (
        result["kind"] == "org"
        and roles == ["owner", "head_uw"]
        and settings["allowed_domains"] == ["newco.re"]
    )
    with plat.tx() as c, pytest.raises(ModelError):
        registration.confirm(
            c, link(plat, "founder@newco.re"), REQ
        )  # the link works once


def test_join_request_reaches_admins_only_after_confirmation_and_needs_approval(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        registration.start(c, "join", "ula@join.re", "Ula User", PW, request=REQ)
        assert (
            registration.list_requests(c, admin) == []
        )  # not confirmed yet: invisible
    with plat.tx() as c:
        result = registration.confirm(c, link(plat, "ula@join.re"), REQ)
        requests = registration.list_requests(c, admin)
        user_id = requests[0]["id"]
        assert identity.user_orgs(c, user_id) == [] and registration.pending_orgs(
            c, user_id
        ) == ["Join Re"]
        with pytest.raises(ModelError):  # nobody self-approves into an organisation
            registration.decide(
                c, identity.principal_for(c, user_id, None), user_id, True, ["owner"]
            )
        with pytest.raises(ModelError):  # at least one role is required
            registration.decide(c, admin, user_id, True, [])
        assert registration.decide(c, admin, user_id, True, ["analyst"]) == ["analyst"]
        assert [o["name"] for o in identity.user_orgs(c, user_id)] == ["Join Re"]
        actions = [r.action for r in c.execute(select(audit_events.c.action))]
    assert result["requested"] == ["Join Re"]
    assert {"auth.signup_started", "user.join_requested", "user.join_approved"} <= set(
        actions
    )
    with plat.tx() as c:
        assert any(m["kind"] == "join_approved" for m in recent(c, "ula@join.re"))


def test_declined_request_and_unmatched_domains(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        registration.start(c, "join", "nia@join.re", "Nia", PW, request=REQ)
        registration.start(c, "join", "pat@gmail.com", "Pat", PW, request=REQ)
    with plat.tx() as c:
        registration.confirm(c, link(plat, "nia@join.re"), REQ)
        assert (
            registration.confirm(c, link(plat, "pat@gmail.com"), REQ)["requested"] == []
        )  # public domains never route
        user_id = registration.list_requests(c, admin)[0]["id"]
        registration.decide(c, admin, user_id, False)
        assert (
            registration.list_requests(c, admin) == []
            and registration.pending_orgs(c, user_id) == []
        )
        assert any(m["kind"] == "signup_no_org" for m in recent(c, "pat@gmail.com"))


def test_existing_accounts_are_not_changed_or_revealed(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        before = c.execute(
            select(users.c.password_hash).where(users.c.email == "boss@join.re")
        ).scalar()
        registration.start(
            c,
            "org",
            "boss@join.re",
            "Mallory",
            "another long passphrase 99",
            "Takeover Re",
            request=REQ,
        )
        after = c.execute(
            select(users.c.password_hash).where(users.c.email == "boss@join.re")
        ).scalar()
        assert before == after and any(
            m["kind"] == "signup_existing" for m in recent(c, "boss@join.re")
        )
        assert not any(m["kind"] == "signup_confirm" for m in recent(c, "boss@join.re"))


def test_invitation_completes_an_unconfirmed_registration(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        registration.start(c, "join", "ivy@join.re", "Ivy", PW, request=REQ)
        raw = identity._invite(
            c, admin, org_id, "ivy@join.re", ["underwriter"], [], REQ
        )
        assert identity.invitation_for(c, raw)["has_account"] is False
        user_id, _ = identity.accept_invitation(c, raw, display_name="Ivy", password=PW)
        assert identity.authenticate(c, "ivy@join.re", PW, REQ)["id"] == user_id


def test_registration_input_rules_and_production_switch(plat, monkeypatch):
    with plat.tx() as c:
        with pytest.raises(ModelError):
            registration.start(
                c, "org", "a@b.re", "A", PW, "", request=REQ
            )  # organisation name
        with pytest.raises(ModelError):
            registration.start(c, "join", "a@b.re", "", PW, request=REQ)  # name
        with pytest.raises(ModelError):
            registration.start(
                c, "join", "a@b.re", "A", "short", request=REQ
            )  # password
        with pytest.raises(ModelError):
            registration.start(
                c, "admin", "a@b.re", "A", PW, request=REQ
            )  # unknown kind
    monkeypatch.setenv("FLOODCAT_ENV", "production")
    assert not registration.signup_enabled()
    monkeypatch.setenv("FLOODCAT_ALLOW_SIGNUP", "1")
    assert registration.signup_enabled()


def test_register_pages_end_to_end(env):  # noqa: F811
    client, plat, _ = env
    assert "Create an account" in client.get("/auth/login").text
    page = client.get("/auth/register")
    assert (
        "Set up a new organisation" in page.text and "Join my organisation" in page.text
    )
    token = csrf(client, "/auth/register?kind=org")
    r = client.post(
        "/auth/register?kind=org",
        data={
            "org_name": "Web Re",
            "display_name": "Wes",
            "email": "wes@web.re",
            "password": PW,
            "confirm": PW,
            "csrf": token,
        },
    )
    assert r.status_code == 200 and "Check your e-mail" in r.text
    confirm = re.search(r'href="[^"]*(/auth/register/confirm/[^"]+)"', r.text).group(
        1
    )  # development link shown (no mail service)
    r = client.get(confirm)
    assert r.status_code == 303 and "xpat_session" in r.headers.get("set-cookie", "")
    bad = client.post(
        "/auth/register?kind=join",
        data={
            "display_name": "X",
            "email": "x@web.re",
            "password": PW,
            "confirm": "nope",
            "csrf": csrf(client, "/auth/register?kind=join"),
        },
    )
    assert bad.status_code == 400 and "do not match" in bad.text


def test_pending_member_sees_why_sign_in_waits(env):  # noqa: F811
    client, plat, org_id = env
    with plat.tx() as c:
        from floodcat.platform import orgs

        owner_raw = identity._invite(
            c, None, org_id, "own2@acme.re", ["owner"], [], REQ, check_domain=False
        )
        uid_, _ = identity.accept_invitation(
            c, owner_raw, display_name="Own", password=PW
        )
        c.execute(
            __import__("sqlalchemy")
            .update(
                __import__(
                    "floodcat.platform.db", fromlist=["organisations"]
                ).organisations
            )
            .values(
                settings={
                    **identity.settings_for(c, org_id),
                    "allowed_domains": ["acme.re"],
                }
            )
        )
        registration.start(c, "join", "new@acme.re", "Newbie", PW, request=REQ)
    with plat.tx() as c:
        registration.confirm(c, link(plat, "new@acme.re"), REQ)
    r = client.post(
        "/auth/login",
        data={
            "email": "new@acme.re",
            "password": PW,
            "csrf": csrf(client, "/auth/login"),
        },
    )
    assert r.status_code == 400 and "waiting for an administrator" in r.text
