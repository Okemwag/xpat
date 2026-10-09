"""Self-service registration: a new organisation with the registrant as administrator, or a request to join that an
administrator approves. One step, no e-mail confirmation; never a way to become an administrator of someone else's
organisation."""

from datetime import timedelta
import pytest
from sqlalchemy import select, update
from floodcat.core.errors import ModelError
from floodcat.platform import identity, registration
from floodcat.platform.db import audit_events, memberships, organisations, users
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


def test_new_organisation_makes_the_registrant_its_administrator_at_once(plat):
    with plat.tx() as c:
        result = registration.register(
            c, "org", "founder@newco.re", "Fay Founder", PW, "NewCo Re", request=REQ
        )
        roles = c.execute(
            select(memberships.c.roles).where(memberships.c.org_id == result["org_id"])
        ).scalar()
        settings = identity.settings_for(c, result["org_id"])
        assert (
            identity.authenticate(c, "founder@newco.re", PW, REQ)["status"] == "active"
        )
        assert not any(
            "confirm" in (m["kind"] or "") for m in recent(c, "founder@newco.re")
        )  # no confirmation e-mail
    assert (
        result["kind"] == "org"
        and roles == ["owner", "head_uw"]
        and settings["allowed_domains"] == ["newco.re"]
    )


def test_join_request_needs_approval(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        result = registration.register(
            c, "join", "ula@join.re", "Ula User", PW, request=REQ
        )
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
        assert any(m["kind"] == "join_approved" for m in recent(c, "ula@join.re"))
    assert result["requested"] == ["Join Re"]
    assert {"auth.signup", "user.join_requested", "user.join_approved"} <= set(actions)


def test_declined_request_and_unmatched_domains(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        registration.register(c, "join", "nia@join.re", "Nia", PW, request=REQ)
        with pytest.raises(
            ModelError, match="organisation code"
        ):  # public domains never route
            registration.register(c, "join", "pat@gmail.com", "Pat", PW, request=REQ)
        assert not c.execute(
            select(users.c.id).where(users.c.email == "pat@gmail.com")
        ).scalar()
        user_id = registration.list_requests(c, admin)[0]["id"]
        registration.decide(c, admin, user_id, False)
        assert (
            registration.list_requests(c, admin) == []
            and registration.pending_orgs(c, user_id) == []
        )


def test_existing_accounts_are_not_changed(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        before = c.execute(
            select(users.c.password_hash).where(users.c.email == "boss@join.re")
        ).scalar()
        with pytest.raises(ModelError, match="already exists"):
            registration.register(
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
        assert before == after
        assert (
            c.execute(
                select(organisations.c.id).where(organisations.c.name == "Takeover Re")
            ).scalar()
            is None
        )


def test_registration_input_rules_and_production_switch(plat, monkeypatch):
    with plat.tx() as c:
        # The organisation name is optional: a blank one becomes the person's own workspace, ready to use.
        result = registration.register(c, "org", "solo@b.re", "Sam Solo", PW, "", request=REQ)
        org = identity.settings_for(c, result["org_id"])
        assert org["mfa_policy"] == "off"
        name = c.execute(select(organisations.c.name).where(organisations.c.id == result["org_id"])).scalar()
        assert name == "Sam Solo's workspace"
        with pytest.raises(ModelError):
            registration.register(c, "join", "a@b.re", "", PW, request=REQ)  # name
        with pytest.raises(ModelError):
            registration.register(
                c, "org", "a@b.re", "A", "short", "Org", request=REQ
            )  # password
        with pytest.raises(ModelError):
            registration.register(
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
    assert "Create your account" in page.text and "I&#39;m an administrator" not in page.text  # no chooser
    r = client.post(
        "/auth/register?kind=org",
        data={
            "display_name": "Wes",
            "email": "wes@web.re",
            "password": PW,
            "csrf": csrf(client, "/auth/register?kind=org"),
        },
    )  # no company and no confirmation needed
    assert r.status_code == 303 and "xpat_session" in r.headers.get(
        "set-cookie", ""
    )  # signed straight in
    assert r.headers["location"] == "http://testserver/app"  # straight to the dashboard
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


def test_join_request_page_and_pending_sign_in_message(env):  # noqa: F811
    client, plat, org_id = env
    with plat.tx() as c:
        c.execute(
            update(organisations)
            .where(organisations.c.id == org_id)
            .values(
                settings={
                    **identity.settings_for(c, org_id),
                    "allowed_domains": ["acme.re"],
                }
            )
        )
    r = client.post(
        "/auth/register?kind=join",
        data={
            "display_name": "Newbie",
            "email": "new@acme.re",
            "password": PW,
            "confirm": PW,
            "csrf": csrf(client, "/auth/register?kind=join"),
        },
    )
    assert r.status_code == 200 and "Request sent" in r.text and "Acme Re" in r.text
    r = client.post(
        "/auth/login",
        data={
            "email": "new@acme.re",
            "password": PW,
            "csrf": csrf(client, "/auth/login"),
        },
    )
    assert r.status_code == 400 and "waiting for an administrator" in r.text


def test_sign_in_and_registration_have_no_role_switch(env):  # noqa: F811
    client, plat, _ = env
    login = client.get("/auth/login").text
    assert "<h1>Sign in" in login and 'class="on"' not in login and "?as=admin" not in login
    form = client.get("/auth/register").text
    assert "Create your account" in form and "kind=join" in form  # joining by code is still reachable
    join = client.get("/auth/register?kind=join").text
    assert "Join your organisation" in join and "org_code" in join


def test_organisation_code_lets_anyone_ask_to_join_and_still_needs_approval(plat):
    org_id, admin = org_with_domain(plat)
    with plat.tx() as c:
        code = registration.join_code(c, admin)
        assert registration.join_code(c, admin) == code  # stable until regenerated
        assert len(code) == 9 and code[4] == "-"
        with pytest.raises(ModelError, match="not recognised"):
            registration.register(
                c, "join", "pat@gmail.com", "Pat", PW, request=REQ, org_code="ZZZZ-ZZZZ"
            )
        result = registration.register(
            c,
            "join",
            "pat@gmail.com",
            "Pat",
            PW,
            request=REQ,
            org_code=code.lower().replace("-", " "),
        )
        assert (
            result["requested"] == ["Join Re"]
            and identity.user_orgs(c, result["user_id"]) == []
        )
        new = registration.join_code(c, admin, regenerate=True)
        assert new != code
        with pytest.raises(
            ModelError, match="not recognised"
        ):  # the old code stops working
            registration.register(
                c, "join", "sam@gmail.com", "Sam", PW, request=REQ, org_code=code
            )
        with pytest.raises(ModelError):  # not through general settings
            from floodcat.platform import orgs

            orgs.update_settings(c, admin, {"join_code": "AAAA-BBBB"})
        with pytest.raises(ModelError):  # members without users.manage cannot see it
            registration.join_code(
                c, identity.principal_for(c, result["user_id"], None)
            )


def test_new_organisations_get_a_code(plat):
    with plat.tx() as c:
        result = registration.register(
            c, "org", "fay@newco.re", "Fay", PW, "NewCo Re", request=REQ
        )
        assert identity.settings_for(c, result["org_id"])["join_code"]


def test_second_click_on_create_account_signs_in_instead_of_failing(env):  # noqa: F811
    client, plat, _ = env
    form = {
        "org_name": "Twice Re",
        "display_name": "Tia",
        "email": "tia@twice.re",
        "password": PW,
        "confirm": PW,
    }
    first = client.post(
        "/auth/register?kind=org",
        data={**form, "csrf": csrf(client, "/auth/register?kind=org")},
    )
    second = client.post(
        "/auth/register?kind=org",
        data={**form, "csrf": csrf(client, "/auth/register?kind=org")},
    )
    assert first.status_code == 303 and second.status_code == 303
    assert "xpat_session" in second.headers.get("set-cookie", "")
    wrong = client.post(
        "/auth/register?kind=org",
        data={
            **form,
            "password": "a different long passphrase 7",
            "confirm": "a different long passphrase 7",
            "csrf": csrf(client, "/auth/register?kind=org"),
        },
    )
    assert wrong.status_code == 400 and "already exists" in wrong.text
    with plat.tx() as c:
        assert (
            c.execute(
                select(organisations.c.id).where(organisations.c.name == "Twice Re")
            )
            .all()
            .__len__()
            == 1
        )


def test_join_form_has_code_field_and_submit_guard(env):  # noqa: F811
    client, plat, _ = env
    page = client.get("/auth/register?kind=join").text
    assert 'name="org_code"' in page and "b.disabled=true" in page


def test_sign_in_throttles_are_off_outside_production_but_quotas_stay(plat, monkeypatch):
    from floodcat.platform import orgs

    monkeypatch.delenv("FLOODCAT_AUTH_THROTTLE", raising=False)
    monkeypatch.delenv("FLOODCAT_ENV", raising=False)
    with plat.tx() as c:
        for i in range(6):  # well past the 3-per-hour limit for one address
            identity.rate_limit(c, "signup:repeat@b.re", 3, timedelta(hours=1))
        assert not identity.auth_throttling()
        result = registration.register(c, "org", "quota@b.re", "Quinn", PW, "", request=REQ)
        owner = identity.principal_for(
            c, result["user_id"], result["org_id"]
        )
        monkeypatch.setenv("FLOODCAT_QUOTA_AI_USER_PER_HOUR", "2")
        orgs.check_ai_quota(c, owner)
        orgs.check_ai_quota(c, owner)
        with pytest.raises(ModelError):
            orgs.check_ai_quota(c, owner)  # spending quotas still apply
    monkeypatch.setenv("FLOODCAT_ENV", "production")
    assert identity.auth_throttling()
    with plat.tx() as c, pytest.raises(ModelError):
        for i in range(4):
            identity.rate_limit(c, "signup:prod@b.re", 3, timedelta(hours=1))


def test_links_follow_the_browser_host_unless_urls_are_configured(monkeypatch):
    monkeypatch.delenv("FLOODCAT_APP_URL", raising=False)
    monkeypatch.delenv("FLOODCAT_AUTH_URL", raising=False)
    monkeypatch.delenv("FLOODCAT_AUTH_PORT", raising=False)
    identity.use_request_host("192.168.1.20:8501")
    # Sign-in pages share the interface's address by default (app/asgi_app.py)…
    assert identity.app_url() == "http://192.168.1.20:8501" and identity.auth_url() == "http://192.168.1.20:8501"
    monkeypatch.setenv("FLOODCAT_AUTH_PORT", "8000")  # …or live on port 8000 with run_app.py --two-servers
    assert identity.auth_url() == "http://192.168.1.20:8000"
    identity.use_request_host("localhost:8501")  # Windows resolves localhost to IPv6 first; servers listen on IPv4
    assert identity.app_url() == "http://127.0.0.1:8501"
    identity.use_request_host("evil.example/<script>")  # not a host name: ignored
    assert identity.auth_url() == "http://127.0.0.1:8000"
    monkeypatch.delenv("FLOODCAT_AUTH_PORT")
    monkeypatch.setenv("FLOODCAT_APP_URL", "https://app.xpat.example/")
    identity.use_request_host("192.168.1.20")
    assert identity.app_url() == "https://app.xpat.example"  # configured URLs always win
    identity.use_request_host(None)


def test_auth_server_root_goes_to_the_app(env):  # noqa: F811
    client, plat, _ = env
    r = client.get("/")
    assert r.status_code == 307 and r.headers["location"] == "http://testserver/app"
    assert 'class="brand" href="http://testserver/app"' in client.get("/auth/login").text
