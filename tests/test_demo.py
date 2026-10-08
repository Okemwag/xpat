"""Demo organisation seeding and one-click demo sign-in: idempotent, audited, no e-mail, never in production."""

import json
import pytest
from sqlalchemy import select
from floodcat.core.errors import ModelError
from floodcat.platform import demo, identity
from floodcat.platform.db import audit_events, memberships, outbox, users
from floodcat.platform.rbac import PERMISSIONS
from test_platform import no_network, p  # noqa: F401  (pytest fixtures)

PW = "storm-a1b2c3-basin-flood"


@pytest.fixture(autouse=True)
def not_production(monkeypatch):
    monkeypatch.delenv("FLOODCAT_ENV", raising=False)
    monkeypatch.delenv("FLOODCAT_DEMO_LOGINS", raising=False)


def test_seed_creates_one_working_account_per_role(p):
    with p.tx() as c:
        result = demo.seed(c, PW)
        assert result["created_org"] and sorted(result["created"]) == sorted(r for r, _ in demo.ACCOUNTS)
        org_id = result["org_id"]
        assert identity.settings_for(c, org_id)["mfa_policy"] == "off"
        for role, _ in demo.ACCOUNTS:
            user = identity.authenticate(c, demo.email_for(role), PW)
            assert user["status"] == "active" and user["email_verified_at"] is not None
            principal = identity.principal_for(c, user["id"], org_id)
            assert principal.roles == (role,) and principal.permissions == PERMISSIONS[role]
        assert c.execute(select(outbox)).first() is None  # nothing e-mailed to the .test addresses


def test_seeding_again_changes_nothing_unless_asked(p):
    with p.tx() as c:
        demo.seed(c, PW)
        again = demo.seed(c, "ridge-99f0e1-delta-flood")
        assert again["created"] == [] and not again["created_org"] and again["reset"] == []
        identity.authenticate(c, demo.email_for("analyst"), PW)  # old password still works
        reset = demo.seed(c, "ridge-99f0e1-delta-flood", reset_password=True)
        assert sorted(reset["reset"]) == sorted(r for r, _ in demo.ACCOUNTS)
        identity.authenticate(c, demo.email_for("analyst"), "ridge-99f0e1-delta-flood")
        assert c.execute(select(memberships).where(memberships.c.org_id == reset["org_id"])).all().__len__() == 8


def test_seed_is_audited_without_the_password(p):
    with p.tx() as c:
        demo.seed(c, PW)
        details = [r.details for r in c.execute(select(audit_events).where(audit_events.c.action.like("demo.%")))]
        assert len(details) == 1 + len(demo.ACCOUNTS)
        assert PW not in json.dumps(details)


def test_weak_password_is_refused(p):
    with p.tx() as c, pytest.raises(ModelError):
        demo.seed(c, "short")


def test_never_in_production(p, monkeypatch):
    monkeypatch.setenv("FLOODCAT_ENV", "production")
    monkeypatch.setenv("FLOODCAT_DEMO_LOGINS", "1")
    assert not demo.logins_enabled()
    with p.tx() as c, pytest.raises(ModelError):
        demo.seed(c, PW)


def test_one_click_session_needs_the_switch_and_a_seeded_account(p, monkeypatch):
    with p.tx() as c:
        with pytest.raises(ModelError):
            demo.demo_session(c, "underwriter")  # switch off by default
        monkeypatch.setenv("FLOODCAT_DEMO_LOGINS", "1")
        with pytest.raises(ModelError) as exc:
            demo.demo_session(c, "underwriter")
        assert exc.value.code == "not_seeded"
        demo.seed(c, PW)
        raw = demo.demo_session(c, "head_uw")
        principal, _ = identity.resolve_session(c, raw)
        assert principal.roles == ("head_uw",) and principal.email == demo.email_for("head_uw")
        with pytest.raises(ModelError):
            demo.demo_session(c, "platform_admin")
        assert c.execute(select(audit_events.c.id).where(audit_events.c.action == "auth.demo_login")).first()


def test_sample_run_is_shared_with_the_whole_organisation_once(p):
    pytest.importorskip("rasterio")
    from floodcat.platform import data
    from floodcat.services.runtime import Runtime

    with p.tx() as c:
        result = demo.seed(c, PW)
        rt = Runtime()
        assert demo.seed_sample_run(c, rt) is not None
        assert demo.seed_sample_run(c, rt) is None  # not saved twice
        viewer_id = c.execute(select(users.c.id).where(users.c.email == demo.email_for("viewer"))).scalar()
        viewer = identity.principal_for(c, viewer_id, result["org_id"])
        assert [r["label"] for r in data.list_runs(c, viewer)] == ["Nairobi starter portfolio (synthetic)"]


def test_demo_route_signs_in_with_one_click(tmp_path, monkeypatch):
    pytest.importorskip("rasterio")

    from fastapi.testclient import TestClient
    from floodcat.platform.service import Platform
    import floodcat.platform.service as service
    import floodcat.platform.web as web
    import floodcat.api.app as api
    from floodcat.services.runtime import Runtime
    from conftest import DATA

    monkeypatch.setenv("FLOODCAT_BREACH_CHECK", "0")
    monkeypatch.setenv("FLOODCAT_APP_URL", "http://testserver/app")
    monkeypatch.setenv("FLOODCAT_AUTH_URL", "http://testserver")
    plat = Platform(f"sqlite:///{tmp_path}/platform.db")
    for mod in (service, web, api):
        monkeypatch.setattr(mod, "platform", lambda url=None: plat)
    client = TestClient(api.create_app(Runtime(data_dir=DATA, store_dir=tmp_path)), follow_redirects=False)
    assert client.get("/auth/demo/underwriter").status_code == 404  # off by default
    monkeypatch.setenv("FLOODCAT_DEMO_LOGINS", "1")
    assert client.get("/auth/demo/underwriter").status_code == 400  # not seeded yet
    with plat.tx() as c:
        demo.seed(c, PW)
    r = client.get("/auth/demo/underwriter")
    assert r.status_code in (302, 303) and r.headers["location"] == "http://testserver/app"
    assert "xpat_session" in r.headers.get("set-cookie", "")


def test_generated_passwords_pass_the_policy():
    from floodcat.platform import security

    for _ in range(20):
        security.check_password(demo.new_password(), demo.email_for("owner"), (demo.DEMO_ORG,))
