"""Authentication web pages (FastAPI). Issues the HttpOnly session cookie the Streamlit app reads.

Routes live under /auth. In production a reverse proxy serves /auth and /v1 from FastAPI and everything else from
Streamlit on one domain; locally they share `localhost` on different ports, which cookies allow.
"""

import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlparse
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from ..core.errors import ModelError
from . import identity, security, sso
from .db import memberships, organisations, users
from .service import platform

SESSION_COOKIE = "xpat_session"
CSRF_COOKIE = "xpat_csrf"
SSO_COOKIE = "xpat_sso"
templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
router = APIRouter(prefix="/auth")


def secure_cookies():
    return (
        os.getenv(
            "FLOODCAT_COOKIE_SECURE",
            "1" if os.getenv("FLOODCAT_ENV") == "production" else "0",
        )
        == "1"
    )


def req_info(request):
    ip = request.client.host if request.client else None
    if os.getenv("FLOODCAT_TRUST_PROXY") == "1" and request.headers.get(
        "x-forwarded-for"
    ):
        ip = request.headers["x-forwarded-for"].split(",")[0].strip()
    return {
        "ip": ip,
        "user_agent": request.headers.get("user-agent", ""),
        "request_id": request.headers.get("x-request-id") or secrets.token_hex(8),
    }


def safe_next(value):
    """Only redirect back into our own app (no open redirects)."""
    app = identity.app_url()
    value = str(value or "")
    if value.startswith(app) or (value.startswith("/") and not value.startswith("//")):
        return value if value.startswith(app) else app + value
    return app


def page(
    request,
    title,
    *,
    lead=None,
    fields=None,
    action="",
    submit="Continue",
    error=None,
    message=None,
    choices=None,
    button=None,
    links=None,
    status=200,
):
    csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    html = templates.get_template("form.html").render(
        title=title,
        lead=lead,
        fields=fields,
        action=action,
        submit=submit,
        error=error,
        message=message,
        choices=choices,
        button=button,
        links=links,
        csrf=csrf,
    )
    response = HTMLResponse(html, status_code=status)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=True,
        samesite="strict",
        secure=secure_cookies(),
        path="/auth",
    )
    return response


def check_csrf(request, token):
    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not token or not secrets.compare_digest(cookie, token):
        raise ModelError("csrf", "Your form expired. Reload the page and try again.")


def with_session(response, raw, max_hours=12):
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(),
        path="/",
        max_age=max_hours * 3600,
    )
    return response


def redirect(url):
    return RedirectResponse(url, status_code=303)


LOGIN_FIELDS = [
    {
        "name": "email",
        "label": "Work e-mail",
        "type": "email",
        "autocomplete": "username",
    },
    {
        "name": "password",
        "label": "Password",
        "type": "password",
        "autocomplete": "current-password",
    },
]


def _login_links(next_url):
    links = [
        {"href": "/auth/forgot", "label": "Forgot password?"},
        {
            "href": f"/auth/sso?next={quote(next_url)}",
            "label": "Sign in with your company (SSO)",
        },
    ]
    if os.getenv("FLOODCAT_ALLOW_GUEST") == "1":
        links.append({"href": "/auth/guest", "label": "Explore the demo"})
    return links


# Sign in ------------------------------------------------------------------------------------------------
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return page(
        request,
        "Sign in",
        lead="Use your work e-mail. New users join by invitation from their administrator.",
        fields=LOGIN_FIELDS,
        action=f"/auth/login?next={quote(next)}",
        submit="Sign in",
        links=_login_links(next),
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf: str = Form(""),
    next: str = "/",
):
    info = req_info(request)
    fail = lambda msg: page(
        request,
        "Sign in",
        fields=[{**LOGIN_FIELDS[0], "value": email}, LOGIN_FIELDS[1]],
        action=f"/auth/login?next={quote(next)}",
        submit="Sign in",
        error=msg,
        links=_login_links(next),
        status=400,
    )
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            user = identity.authenticate(conn, email, password, info)
            if sso.sso_enforced_for(conn, user["id"]):
                raise ModelError(
                    "sso_required",
                    "Your organisation requires sign-in through your company account (SSO).",
                )
            orgs = identity.user_orgs(conn, user["id"])
            if not orgs and not user["is_platform_admin"]:
                raise ModelError(
                    "no_org", "Your account is not active in any organisation."
                )
            org_id = orgs[0]["id"] if len(orgs) == 1 else None
            raw, _ = identity.start_session(
                conn,
                user["id"],
                org_id,
                mfa_passed=user["mfa_enabled_at"] is None,
                request=info,
            )
            settings = (
                identity.settings_for(conn, org_id)
                if org_id
                else identity.DEFAULT_SETTINGS
            )
    except ModelError as exc:
        return fail(str(exc))
    target = (
        f"/auth/mfa?next={quote(next)}"
        if user["mfa_enabled_at"]
        else (
            f"/auth/choose-org?next={quote(next)}"
            if org_id is None and orgs
            else safe_next(next)
        )
    )
    return with_session(redirect(target), raw, settings["session_max_hours"])


MFA_FIELD = [
    {
        "name": "code",
        "label": "Authentication code",
        "autocomplete": "one-time-code",
        "inputmode": "numeric",
        "hint": "The 6-digit code from your authenticator app, or one of your recovery codes.",
    }
]


@router.get("/mfa", response_class=HTMLResponse)
def mfa_form(request: Request, next: str = "/"):
    return page(
        request,
        "Two-step verification",
        fields=MFA_FIELD,
        action=f"/auth/mfa?next={quote(next)}",
        submit="Verify",
    )


@router.post("/mfa")
def mfa(request: Request, code: str = Form(""), csrf: str = Form(""), next: str = "/"):
    raw = request.cookies.get(SESSION_COOKIE)
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            identity.complete_mfa(conn, raw, code, req_info(request))
            principal, _ = identity.resolve_session(conn, raw)
    except ModelError as exc:
        return page(
            request,
            "Two-step verification",
            fields=MFA_FIELD,
            action=f"/auth/mfa?next={quote(next)}",
            submit="Verify",
            error=str(exc),
            status=400,
        )
    if principal is not None and principal.org_id is None:
        return redirect(f"/auth/choose-org?next={quote(next)}")
    return redirect(safe_next(next))


@router.get("/choose-org", response_class=HTMLResponse)
def choose_org(request: Request, next: str = "/"):
    with platform().tx() as conn:
        principal, _ = identity.resolve_session(
            conn, request.cookies.get(SESSION_COOKIE)
        )
        if principal is None:
            return redirect(f"/auth/login?next={quote(next)}")
        orgs = identity.user_orgs(conn, principal.user_id)
    return page(
        request,
        "Choose an organisation",
        fields=None,
        choices=[
            {
                "href": f"/auth/switch-org/{o['id']}?next={quote(next)}",
                "label": f"{o['name']} — {', '.join(o['roles'])}",
            }
            for o in orgs
        ],
    )


@router.get("/switch-org/{org_id}")
def switch_org(request: Request, org_id: str, next: str = "/"):
    try:
        with platform().tx() as conn:
            identity.switch_org(
                conn, request.cookies.get(SESSION_COOKIE), org_id, req_info(request)
            )
    except ModelError as exc:
        return page(request, "Choose an organisation", error=str(exc), status=403)
    return redirect(safe_next(next))


@router.get("/logout")
def logout(request: Request):
    with platform().tx() as conn:
        identity.logout(conn, request.cookies.get(SESSION_COOKIE), req_info(request))
    response = redirect(identity.app_url())
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# Forgot / reset password (FLOW-03) ----------------------------------------------------------------------
@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request):
    return page(
        request,
        "Reset your password",
        lead="Enter your work e-mail and we will send a reset link.",
        fields=[{**LOGIN_FIELDS[0]}],
        action="/auth/forgot",
        submit="Send reset link",
        links=[{"href": "/auth/login", "label": "Back to sign in"}],
    )


@router.post("/forgot", response_class=HTMLResponse)
def forgot(request: Request, email: str = Form(""), csrf: str = Form("")):
    try:
        check_csrf(request, csrf)
    except ModelError as exc:
        return page(
            request,
            "Reset your password",
            error=str(exc),
            fields=[LOGIN_FIELDS[0]],
            action="/auth/forgot",
            status=400,
        )
    with platform().tx() as conn:
        identity.forgot_password(conn, email, req_info(request))
    return page(
        request,
        "Check your e-mail",
        message="If an account exists for that address, a reset link is on its way. It expires in 30 minutes.",
        links=[{"href": "/auth/login", "label": "Back to sign in"}],
    )


def _reset_fields(needs_mfa):
    fields = [
        {
            "name": "password",
            "label": "New password",
            "type": "password",
            "autocomplete": "new-password",
            "hint": f"At least {security.MIN_PASSWORD} characters. A short sentence is easy to remember and hard to guess.",
        },
        {
            "name": "confirm",
            "label": "Confirm new password",
            "type": "password",
            "autocomplete": "new-password",
        },
    ]
    return fields + (MFA_FIELD if needs_mfa else [])


@router.get("/reset/{token}", response_class=HTMLResponse)
def reset_form(request: Request, token: str):
    try:
        with platform().tx() as conn:
            needs = identity.reset_needs_mfa(conn, token)
    except ModelError as exc:
        return page(
            request,
            "Link expired",
            error=str(exc),
            links=[{"href": "/auth/forgot", "label": "Request a new link"}],
            status=400,
        )
    return page(
        request,
        "Choose a new password",
        fields=_reset_fields(needs),
        action=f"/auth/reset/{token}",
        submit="Save password",
    )


@router.post("/reset/{token}", response_class=HTMLResponse)
def reset(
    request: Request,
    token: str,
    password: str = Form(""),
    confirm: str = Form(""),
    code: str = Form(""),
    csrf: str = Form(""),
):
    needs = False
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            needs = identity.reset_needs_mfa(conn, token)
        if password != confirm:
            raise ModelError("mismatch", "The passwords do not match")
        with platform().tx() as conn:
            identity.reset_password(conn, token, password, code, req_info(request))
    except ModelError as exc:
        return page(
            request,
            "Choose a new password",
            fields=_reset_fields(needs),
            action=f"/auth/reset/{token}",
            submit="Save password",
            error=str(exc),
            status=400,
        )
    return page(
        request,
        "Password changed",
        message="Your password was changed and all sessions were signed out.",
        button={"href": "/auth/login", "label": "Sign in"},
    )


# Invitations (FLOW-01) ----------------------------------------------------------------------------------
def _invite_fields(inv):
    if inv["has_account"]:
        return [
            {
                "name": "existing_password",
                "label": "Your current Xpat password",
                "type": "password",
                "autocomplete": "current-password",
            }
        ]
    return [
        {"name": "display_name", "label": "Your name", "autocomplete": "name"}
    ] + _reset_fields(False)


@router.get("/invite/{token}", response_class=HTMLResponse)
def invite_form(request: Request, token: str):
    try:
        with platform().tx() as conn:
            inv = identity.invitation_for(conn, token)
    except ModelError as exc:
        return page(request, "Invitation unavailable", error=str(exc), status=400)
    return page(
        request,
        f"Join {inv['org_name']}",
        lead=f"You were invited as {', '.join(inv['roles'])} ({inv['email']}).",
        fields=_invite_fields(inv),
        action=f"/auth/invite/{token}",
        submit="Join organisation",
    )


@router.post("/invite/{token}", response_class=HTMLResponse)
def accept(
    request: Request,
    token: str,
    display_name: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    existing_password: str = Form(""),
    csrf: str = Form(""),
):
    info = req_info(request)
    inv = None
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            inv = identity.invitation_for(conn, token)
        if not inv["has_account"] and password != confirm:
            raise ModelError("mismatch", "The passwords do not match")
        with platform().tx() as conn:
            user_id, org_id = identity.accept_invitation(
                conn, token, display_name, password, existing_password, request=info
            )
            mfa_on = (
                conn.execute(
                    select(users.c.mfa_enabled_at).where(users.c.id == user_id)
                ).scalar()
                is not None
            )
            raw, _ = identity.start_session(
                conn, user_id, org_id, mfa_passed=not mfa_on, request=info
            )
    except ModelError as exc:
        if inv is None:
            return page(request, "Invitation unavailable", error=str(exc), status=400)
        return page(
            request,
            f"Join {inv['org_name']}",
            fields=_invite_fields(inv),
            action=f"/auth/invite/{token}",
            submit="Join organisation",
            error=str(exc),
            status=400,
        )
    return with_session(redirect("/auth/mfa" if mfa_on else identity.app_url()), raw)


@router.get("/verify-email/{token}", response_class=HTMLResponse)
def verify_email(request: Request, token: str):
    try:
        with platform().tx() as conn:
            identity.confirm_email_change(conn, token, req_info(request))
    except ModelError as exc:
        return page(request, "Link expired", error=str(exc), status=400)
    return page(
        request,
        "E-mail confirmed",
        message="Your sign-in e-mail was changed. Sign in again with the new address.",
        button={"href": "/auth/login", "label": "Sign in"},
    )


# Step-up (AUTH-17) --------------------------------------------------------------------------------------
@router.get("/reauth", response_class=HTMLResponse)
def reauth_form(request: Request, next: str = "/"):
    with platform().tx() as conn:
        principal, _ = identity.resolve_session(
            conn, request.cookies.get(SESSION_COOKIE)
        )
    if principal is None:
        return redirect(f"/auth/login?next={quote(next)}")
    fields = [
        {
            "name": "password",
            "label": "Password",
            "type": "password",
            "autocomplete": "current-password",
            "required": False,
        }
    ]
    if principal.extra.get("mfa_enabled"):
        fields += [{**MFA_FIELD[0], "required": False}]
    return page(
        request,
        "Confirm it is you",
        lead="This action needs your password (or an authentication code) again.",
        fields=fields,
        action=f"/auth/reauth?next={quote(next)}",
        submit="Confirm",
    )


@router.post("/reauth")
def reauth(
    request: Request,
    password: str = Form(""),
    code: str = Form(""),
    csrf: str = Form(""),
    next: str = "/",
):
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            principal, _ = identity.resolve_session(
                conn, request.cookies.get(SESSION_COOKIE)
            )
            if principal is None:
                return redirect(f"/auth/login?next={quote(next)}")
            identity.reauthenticate(
                conn, principal, password or None, code or None, req_info(request)
            )
    except ModelError as exc:
        return page(
            request,
            "Confirm it is you",
            error=str(exc),
            fields=[
                {
                    "name": "password",
                    "label": "Password",
                    "type": "password",
                    "required": False,
                },
                {**MFA_FIELD[0], "required": False},
            ],
            action=f"/auth/reauth?next={quote(next)}",
            submit="Confirm",
            status=400,
        )
    return redirect(safe_next(next))


# Single sign-on (AUTH-01) ---------------------------------------------------------------------------------
@router.get("/sso", response_class=HTMLResponse)
def sso_form(request: Request, next: str = "/"):
    return page(
        request,
        "Sign in with your company",
        lead="Enter your work e-mail; we will send you to your organisation's sign-in page.",
        fields=[LOGIN_FIELDS[0]],
        action=f"/auth/sso?next={quote(next)}",
        submit="Continue",
        links=[{"href": "/auth/login", "label": "Use a password instead"}],
    )


@router.post("/sso")
def sso_begin(
    request: Request, email: str = Form(""), csrf: str = Form(""), next: str = "/"
):
    try:
        check_csrf(request, csrf)
        with platform().tx() as conn:
            org_id = sso.org_for_email(conn, email)
            if not org_id:
                raise ModelError(
                    "sso_not_configured",
                    "Your organisation has not set up single sign-on. Use your password.",
                )
            url, cookie = sso.start(conn, org_id, safe_next(next))
    except ModelError as exc:
        return page(
            request,
            "Sign in with your company",
            fields=[LOGIN_FIELDS[0]],
            action=f"/auth/sso?next={quote(next)}",
            error=str(exc),
            status=400,
        )
    response = redirect(url)
    response.set_cookie(
        SSO_COOKIE,
        cookie,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(),
        path="/auth/sso",
        max_age=sso.STATE_TTL,
    )
    return response


@router.get("/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return page(
            request,
            "Sign-in cancelled",
            error="Your identity provider did not complete the sign-in.",
            status=400,
        )
    try:
        with platform().tx() as conn:
            raw, next_url = sso.callback(
                conn,
                code,
                state,
                request.cookies.get(SSO_COOKIE),
                request=req_info(request),
            )
    except ModelError as exc:
        return page(
            request,
            "Sign-in failed",
            error=str(exc),
            links=[{"href": "/auth/login", "label": "Back to sign in"}],
            status=400,
        )
    response = with_session(redirect(safe_next(next_url)), raw)
    response.delete_cookie(SSO_COOKIE, path="/auth/sso")
    return response


# Public demo (ORG-09: only when FLOODCAT_ALLOW_GUEST=1) --------------------------------------------------------
DEMO_ORG_NAME = "Public demo"


def ensure_demo(conn):
    from .db import now, uid

    org_id = conn.execute(
        select(organisations.c.id).where(organisations.c.name == DEMO_ORG_NAME)
    ).scalar()
    if not org_id:
        org_id = uid()
        conn.execute(
            organisations.insert().values(
                id=org_id,
                name=DEMO_ORG_NAME,
                status="active",
                plan="demo",
                seats=1_000_000,
                created_at=now(),
                settings={
                    **identity.DEFAULT_SETTINGS,
                    "mfa_policy": "off",
                    "enforce_separation_of_duties": False,
                    "default_visibility": "private",
                    "retention_runs_days": 30,
                },
                profile={},
            )
        )
    return org_id


@router.get("/guest")
def guest(request: Request):
    if os.getenv("FLOODCAT_ALLOW_GUEST") != "1":
        return page(
            request, "Demo unavailable", error="Guest access is turned off.", status=404
        )
    from .db import now, uid

    info = req_info(request)
    with platform().tx() as conn:
        identity.rate_limit(
            conn,
            f"guest-ip:{info['ip']}",
            30,
            identity.timedelta(hours=1),
            "Too many demo sessions from your network",
        )
        org_id = ensure_demo(conn)
        user_id = uid()
        conn.execute(
            users.insert().values(
                id=user_id,
                email=f"guest-{user_id[:10]}@demo.invalid",
                display_name="Guest",
                status="active",
                created_at=now(),
            )
        )
        conn.execute(
            memberships.insert().values(
                id=uid(),
                org_id=org_id,
                user_id=user_id,
                status="active",
                created_at=now(),
                roles=["underwriter", "analyst", "reviewer", "head_uw"],
            )
        )
        raw, _ = identity.start_session(
            conn, user_id, org_id, method="guest", request=info
        )
    return with_session(redirect(identity.app_url()), raw, 4)
