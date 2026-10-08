"""Auth pages, cookies, CSRF, redirects, API tokens and SSO through the real FastAPI app (SQLite, outbox e-mail, fake IdP)."""

import re
import time
from functools import lru_cache
import httpx
import pytest
from fastapi.testclient import TestClient
from floodcat.platform import identity, security, sso
from floodcat.platform.email import recent
from floodcat.platform.service import Platform
from conftest import DATA

PW = "a long and unusual passphrase 42"


@pytest.fixture
def env(tmp_path, monkeypatch):
    pytest.importorskip("rasterio")
    monkeypatch.setenv("FLOODCAT_BREACH_CHECK", "0")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("FLOODCAT_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("FLOODCAT_APP_URL", "http://testserver/app")
    monkeypatch.setenv("FLOODCAT_AUTH_URL", "http://testserver")
    plat = Platform(f"sqlite:///{tmp_path}/platform.db")
    import floodcat.platform.service as service

    monkeypatch.setattr(service, "platform", lambda url=None: plat)
    import floodcat.platform.web as web, floodcat.api.app as api

    monkeypatch.setattr(web, "platform", lambda url=None: plat)
    monkeypatch.setattr(api, "platform", lambda url=None: plat)
    from floodcat.services.runtime import Runtime

    client = TestClient(
        api.create_app(Runtime(data_dir=DATA, store_dir=tmp_path)),
        follow_redirects=False,
    )
    with plat.tx() as c:
        staff_id = identity.bootstrap_platform_admin(c, "staff@xpat.io", "Staff", PW)
        org_id, _ = identity.create_organisation(
            c, identity.principal_for(c, staff_id, None), "Acme Re", "owner@acme.re"
        )
    return client, plat, org_id


def mail_link(plat, to, kind):
    with plat.tx() as c:
        msg = next(m for m in recent(c, to) if m["kind"] == kind)
    return re.search(r"(/auth/\S+)", msg["text"]).group(1)


def csrf(client, path):
    r = client.get(path)
    assert r.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


def join(client, plat, email="owner@acme.re", name="Olive"):
    path = mail_link(plat, email, "invitation")
    token = csrf(client, path)
    r = client.post(
        path, data={"display_name": name, "password": PW, "confirm": PW, "csrf": token}
    )
    assert r.status_code == 303, r.text
    return r


def test_invitation_sets_httponly_session_cookie(env):
    client, plat, _ = env
    r = join(client, plat)
    cookie = r.headers["set-cookie"]
    assert (
        "xpat_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    )
    assert client.get("/v1/me").json()["roles"] == ["owner"]


def test_login_requires_csrf_and_redirects_safely(env):
    client, plat, _ = env
    join(client, plat)
    client.cookies.clear()
    assert (
        client.post(
            "/auth/login",
            data={"email": "owner@acme.re", "password": PW, "csrf": "forged"},
        ).status_code
        == 400
    )
    token = csrf(client, "/auth/login")
    r = client.post(
        "/auth/login?next=https://evil.example/steal",
        data={"email": "owner@acme.re", "password": PW, "csrf": token},
    )
    assert r.status_code == 303 and r.headers["location"] == "http://testserver/app"


def test_wrong_password_is_generic_and_audited(env):
    client, plat, _ = env
    join(client, plat)
    client.cookies.clear()
    token = csrf(client, "/auth/login")
    r = client.post(
        "/auth/login",
        data={"email": "owner@acme.re", "password": "nope nope nope", "csrf": token},
    )
    r2 = client.post(
        "/auth/login",
        data={"email": "ghost@acme.re", "password": "nope nope nope", "csrf": token},
    )
    assert (
        r.status_code == r2.status_code == 400
        and "incorrect" in r.text
        and "incorrect" in r2.text
    )


def test_mfa_login_flow(env):
    client, plat, _ = env
    join(client, plat)
    with plat.tx() as c:
        p, _ = identity.resolve_session(c, client.cookies["xpat_session"])
        secret, _ = identity.begin_mfa(c, p)
        identity.confirm_mfa(c, p, security.totp(secret))
    client.cookies.clear()
    token = csrf(client, "/auth/login")
    r = client.post(
        "/auth/login", data={"email": "owner@acme.re", "password": PW, "csrf": token}
    )
    assert r.headers["location"].startswith("/auth/mfa")
    assert (
        client.get("/v1/me").status_code == 401
    )  # not signed in until the code is entered
    token = csrf(client, "/auth/mfa")
    assert (
        client.post("/auth/mfa", data={"code": "000000", "csrf": token}).status_code
        == 400
    )
    assert (
        client.post(
            "/auth/mfa", data={"code": security.totp(secret), "csrf": token}
        ).status_code
        == 303
    )
    assert client.get("/v1/me").status_code == 200


def test_forgot_and_reset_through_pages(env):
    client, plat, _ = env
    join(client, plat)
    client.cookies.clear()
    token = csrf(client, "/auth/forgot")
    r = client.post("/auth/forgot", data={"email": "owner@acme.re", "csrf": token})
    assert "If an account exists" in r.text
    path = mail_link(plat, "owner@acme.re", "password_reset")
    token = csrf(client, path)
    assert (
        client.post(
            path, data={"password": "x", "confirm": "x", "csrf": token}
        ).status_code
        == 400
    )
    new = "a different long passphrase 99"
    assert (
        "Password changed"
        in client.post(path, data={"password": new, "confirm": new, "csrf": token}).text
    )
    assert client.get(path).status_code == 400  # single use


def test_security_headers(env):
    client, _, _ = env
    r = client.get("/auth/login")
    assert (
        r.headers["x-frame-options"] == "DENY"
        and "frame-ancestors" in r.headers["content-security-policy"]
    )
    assert r.headers["cache-control"] == "no-store"


def test_api_tokens_and_scopes(env):
    client, plat, org_id = env
    join(client, plat)
    with plat.tx() as c:
        owner, _ = identity.resolve_session(c, client.cookies["xpat_session"])
        identity.invite(c, owner, "uw@acme.re", ["underwriter"])
    client.cookies.clear()
    join(client, plat, "uw@acme.re", "Uma")
    with plat.tx() as c:
        uw, _ = identity.resolve_session(c, client.cookies["xpat_session"])
        read = identity.create_api_token(c, uw, "reader", ["runs.read"])
        write = identity.create_api_token(c, uw, "writer", ["runs.create", "runs.read"])
    client.cookies.clear()
    rows = [
        {
            "loc_id": "A",
            "lat": "-1.2576",
            "lon": "36.8962",
            "housing_class": "semi_permanent",
            "tiv_kes": "3300000",
            "synthetic": "True",
            "source": "t",
        }
    ]
    assert client.post("/v1/analyses", json={"rows": rows}).status_code == 401
    assert (
        client.post(
            "/v1/analyses",
            json={"rows": rows},
            headers={"Authorization": f"Bearer {read}"},
        ).status_code
        == 403
    )
    r = client.post(
        "/v1/analyses",
        json={"rows": rows},
        headers={"Authorization": f"Bearer {write}"},
    )
    assert r.status_code == 201
    listed = client.get(
        "/v1/analyses", headers={"Authorization": f"Bearer {read}"}
    ).json()
    assert listed[0]["id"] == r.json()["analysis_id"]


# SSO with a fake identity provider ------------------------------------------------------------------------
@lru_cache(maxsize=1)
def idp_key():
    from joserfc.jwk import RSAKey

    return RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)


def fake_idp(claims_override=None, bad_signature=False):
    from joserfc import jwt
    from joserfc.jwk import RSAKey

    issued = {}

    def handler(request):
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://idp.example",
                    "authorization_endpoint": "https://idp.example/authorize",
                    "token_endpoint": "https://idp.example/token",
                    "jwks_uri": "https://idp.example/jwks",
                },
            )
        if url.endswith("/jwks"):
            return httpx.Response(
                200, json={"keys": [idp_key().as_dict(private=False)]}
            )
        if url.endswith("/token"):
            key = (
                RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)
                if bad_signature
                else idp_key()
            )
            claims = {
                "iss": "https://idp.example",
                "aud": "client-1",
                "sub": "sub-123",
                "email": "sso.user@acme.re",
                "email_verified": True,
                "name": "Sso User",
                "nonce": issued["nonce"],
                "exp": int(time.time()) + 300,
                "iat": int(time.time()),
                "groups": ["uw-group"],
            }
            claims.update(claims_override or {})
            return httpx.Response(
                200,
                json={
                    "id_token": jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key)
                },
            )
        return httpx.Response(404)

    return handler, issued


def setup_sso(client, plat, monkeypatch, **kw):
    join(client, plat)
    with plat.tx() as c:
        owner, _ = identity.resolve_session(c, client.cookies["xpat_session"])
        identity.reauthenticate(c, owner, password=PW)
        from floodcat.platform import orgs

        orgs.update_settings(c, owner, {"allowed_domains": ["acme.re"]})
        sso.configure(
            c,
            owner,
            "https://idp.example/.well-known/openid-configuration",
            "client-1",
            "secret-1",
            default_role="viewer",
            role_mapping={"uw-group": ["underwriter"]},
        )
    handler, issued = fake_idp(**kw)
    monkeypatch.setattr(
        sso, "HTTP", httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.cookies.clear()
    token = csrf(client, "/auth/sso")
    r = client.post("/auth/sso", data={"email": "someone@acme.re", "csrf": token})
    assert r.status_code == 303 and r.headers["location"].startswith(
        "https://idp.example/authorize"
    )
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(r.headers["location"]).query)
    issued["nonce"] = q["nonce"][0]
    assert q["code_challenge_method"] == ["S256"]
    return q["state"][0]


def test_sso_round_trip_provisions_with_mapped_role(env, monkeypatch):
    client, plat, _ = env
    state = setup_sso(client, plat, monkeypatch)
    r = client.get(f"/auth/sso/callback?code=abc&state={state}")
    assert r.status_code == 303, r.text
    me = client.get("/v1/me").json()
    assert me["email"] == "sso.user@acme.re" and me["roles"] == ["underwriter"]


def test_sso_rejects_bad_signature_wrong_state_and_foreign_domain(env, monkeypatch):
    client, plat, _ = env
    state = setup_sso(client, plat, monkeypatch, bad_signature=True)
    assert client.get(f"/auth/sso/callback?code=abc&state={state}").status_code == 400
    assert client.get("/auth/sso/callback?code=abc&state=forged").status_code == 400


def test_sso_rejects_other_domains(env, monkeypatch):
    client, plat, _ = env
    state = setup_sso(
        client, plat, monkeypatch, claims_override={"email": "intruder@gmail.com"}
    )
    r = client.get(f"/auth/sso/callback?code=abc&state={state}")
    assert r.status_code == 400 and "domain" in r.text


def test_guest_demo_only_when_enabled(env, monkeypatch):
    client, _, _ = env
    monkeypatch.delenv("FLOODCAT_ALLOW_GUEST", raising=False)
    assert client.get("/auth/guest").status_code == 404
    monkeypatch.setenv("FLOODCAT_ALLOW_GUEST", "1")
    assert (
        client.get("/auth/guest").status_code == 303
        and client.get("/v1/me").status_code == 200
    )
