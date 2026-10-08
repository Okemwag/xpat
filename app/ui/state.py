"""Session state, shared runtime and formatting for the Streamlit app.

Identity comes from the HttpOnly `xpat_session` cookie issued by the auth pages (FastAPI, /auth). It is resolved on every
rerun, so revocation, idle timeout and role changes take effect immediately.
"""

import os
from decimal import Decimal
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.services.runtime import Runtime

SESSION_COOKIE = "xpat_session"


@st.cache_resource(show_spinner="Loading hazard maps…")
def runtime():
    return Runtime()


@st.cache_resource
def platform():
    from floodcat.platform.service import Platform

    return Platform()


def ai_choice(client_data=False):
    """(provider, reason) for this user's next AI request under the organisation's rules; (None, why) when none may be used."""
    from floodcat.ai.llm import choose

    p = principal()
    try:
        return choose(
            org().get("settings") or {}, p.user_id if p else None, client_data
        )
    except ModelError as exc:
        return None, str(exc)


def llm(client_data=False):
    """The model client for one request. client_data=True for documents, schedules, descriptions and results on real exposure:
    when the organisation keeps client data on its own server, only the local model is used (never a silent cloud fallback)."""
    from floodcat.ai.llm import choose

    p = principal()
    chosen, _ = choose(
        org().get("settings") or {}, p.user_id if p else None, client_data
    )
    st.session_state["ai_provider_used"] = chosen
    return runtime().llm(chosen)


def run_has_client_data(report=None):
    """True when the current results include real (client) exposure."""
    return "REAL" in exposure_labels(report)


def ai_name(client_data=False):
    """The model that will serve this user's request, for consent text and captions."""
    from floodcat.ai.llm import describe

    chosen, _ = ai_choice(client_data)
    return describe(chosen) if chosen else "no model allowed"


def ai_local(client_data=False):
    return ai_choice(client_data)[0] == "ollama"


def ai_available():
    from floodcat.ai.llm import available

    return available()


def guest_allowed():
    return os.getenv("FLOODCAT_ALLOW_GUEST", "0") == "1"


def use_browser_host():
    """Links to the sign-in pages and back follow the address this browser used (unless URLs are configured)."""
    from floodcat.platform.identity import use_request_host

    try:
        host = st.context.headers.get("host")
    except Exception:  # no request context (tests, scripts)
        host = None
    use_request_host(host if isinstance(host, str) else None)


def auth_link(path):
    from floodcat.platform.identity import auth_url

    return auth_url() + path


def request_info():
    def text(value):
        return value if isinstance(value, str) else None

    try:
        return {
            "ip": text(st.context.ip_address),
            "user_agent": text(st.context.headers.get("user-agent", "")),
            "request_id": None,
        }
    except Exception:
        return {}


# Session -----------------------------------------------------------------
def session_token():
    try:
        token = st.context.cookies.get(SESSION_COOKIE)
    except Exception:
        token = None
    if not isinstance(token, str) or not token:
        token = None
    if not token and os.getenv("FLOODCAT_ENV") != "production":
        token = st.session_state.get(
            "_test_session_token"
        )  # tests only; never set by the interface
    return token


def resolve():
    """Resolve the session cookie once per rerun. Returns (principal, reason)."""
    from floodcat.platform import identity

    token = session_token()
    if not token:
        return None, "none"
    with platform().tx() as conn:
        principal, reason = identity.resolve_session(conn, token)
        if principal is not None and principal.org_id:
            from floodcat.platform.orgs import get_org

            org = get_org(conn, principal.org_id)
            st.session_state["org"] = {
                "id": org["id"],
                "name": org["name"],
                "status": org["status"],
                "settings": org["settings"],
                "plan": org["plan"],
            }
            st.session_state["org_count"] = len(
                identity.user_orgs(conn, principal.user_id)
            )
    if principal is None:
        for key in ("result", "rows", "run_label", "org"):
            st.session_state.pop(key, None)
    st.session_state["principal"] = principal
    return principal, reason


def principal():
    return st.session_state.get("principal")


def user():
    """Compatibility view of the signed-in person for display code."""
    p = principal()
    if p is None:
        return None
    return {
        "username": p.email,
        "display_name": p.display_name,
        "role": ", ".join(p.roles)
        or ("platform admin" if p.is_platform_admin else "—"),
        "organisation": org().get("name", ""),
        "guest": p.extra.get("method") == "guest",
        "user_id": p.user_id,
    }


def org():
    return st.session_state.get("org") or {}


def can(permission):
    p = principal()
    return bool(p) and p.can(permission)


def can_review():
    return can("evidence.approve")


def is_admin():
    return any(
        can(x)
        for x in ("users.manage", "security.manage", "audit.read", "settings.manage")
    )


def read_only():
    p = principal()
    return bool(p) and bool(p.extra.get("read_only"))


def ai_mode():
    return org().get("settings", {}).get("ai_mode", "full")


def ai_enabled(kind="extraction"):
    """An AI model configured (Gemini or local Ollama), the organisation allows this AI feature, and the user may use it."""
    if not ai_available() or not can("ai.extract") or ai_choice()[0] is None:
        return False
    mode = ai_mode()
    return mode == "full" or (mode == "extraction" and kind == "extraction")


FAILED = object()


def guarded(fn, *args, **kwargs):
    """Run a platform action. Returns its result, or FAILED after showing the error (with a re-authentication link
    when the action needs a recent password check)."""
    try:
        with platform().tx() as conn:
            return fn(conn, principal(), *args, request=request_info(), **kwargs)
    except ModelError as exc:
        if exc.code == "reauth_required":
            from urllib.parse import quote

            here = getattr(st.context, "url", "") or ""
            st.warning(
                "For your security, confirm your password before this change.",
                icon=":material/lock:",
            )
            st.link_button(
                "Confirm it is you",
                auth_link(f"/auth/reauth?next={quote(here)}"),
                icon=":material/key:",
            )
        else:
            st.error(str(exc), icon=":material/error:")
        return FAILED


def result():
    return st.session_state.get("result")


def set_result(report, rows, label, settings=None):
    st.session_state["result"] = report
    st.session_state["rows"] = rows
    st.session_state["run_label"] = label
    st.session_state["run_settings"] = settings or {}
    st.session_state.pop("ai_result", None)


def house_config():
    from floodcat.core.config import ModelConfig
    from floodcat.platform.data import house_config as house

    p = principal()
    if p is None or not p.org_id:
        return runtime().config
    with platform().tx() as conn:
        return ModelConfig(**house(conn, p.org_id))


def config():
    """The house assumptions of the organisation plus this user's sandbox overrides for the session."""
    base = house_config()
    overrides = st.session_state.get("config_overrides") or {}
    return base.replace(**overrides) if overrides else base


def execute(rows, label, *, settings=None, save=True, **options):
    """Run the model, save it to the organisation's history, and keep it in the session. Returns (report, error)."""
    settings = dict(settings or {})
    if not rows:
        return None, ModelError(
            "no_input",
            "This saved run has no input records; load the portfolio again to re-run it",
        )
    if read_only():
        return None, ModelError(
            "read_only",
            "Your organisation is suspended (read-only). New analyses are disabled.",
        )
    if not can("runs.create"):
        return None, ModelError("forbidden", "Your role cannot run analyses")
    try:
        report = runtime().run(rows, config=config(), **settings, **options)
    except ModelError as exc:
        return None, exc
    if save:
        from floodcat.platform import data

        try:
            with platform().tx() as conn:
                house = data.house_set(conn, principal().org_id)
                data.save_run(
                    conn,
                    principal(),
                    report,
                    rows,
                    label,
                    settings,
                    submission_id=st.session_state.get("active_submission"),
                    assumption_set_id=house["id"]
                    if house and not st.session_state.get("config_overrides")
                    else None,
                    request=request_info(),
                )
                extraction = st.session_state.pop("pending_extraction", None)
                if extraction:
                    data.link_extraction(
                        conn,
                        principal(),
                        extraction["id"],
                        report["analysis_id"],
                        extraction.get("decisions", {}),
                    )
        except ModelError as exc:
            return None, exc
    set_result(report, rows, label, settings)
    return report, None


# Formatting -----------------------------------------------------------------
def kes(value, compact=True):
    v = Decimal(str(value))
    if not compact:
        return f"KES {v:,.0f}"
    a = abs(v)
    if a >= 10**9:
        return f"KES {v / 10**9:,.2f} bn"
    if a >= 10**6:
        return f"KES {v / 10**6:,.1f} m"
    if a >= 10**3:
        return f"KES {v / 10**3:,.0f} k"
    return f"KES {v:,.0f}"


def pct(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}%"


def rp_label(years):
    return f"1-in-{years:g}"


def class_label(name):
    return {
        "informal_iron_sheet": "Informal (iron sheet)",
        "semi_permanent": "Semi-permanent",
        "permanent_masonry": "Permanent masonry",
        "concrete_rcc": "Reinforced concrete",
    }.get(name, name)


def tier_for_rp(cfg, years):
    return next(t for t, rp in cfg.return_periods.items() if rp == years)


def uncertainty(report=None):
    """Monte Carlo ranges for the current result, computed once per analysis and config."""
    from floodcat.exposure.validation import apply_declarations
    from floodcat.financial.uncertainty import uncertainty_ranges

    report = report or result()
    if report is None:
        return None
    cfg = config()
    key = (report["analysis_id"], cfg.fingerprint)
    cached = st.session_state.get("uncertainty")
    if cached and cached[0] == key:
        return cached[1]
    settings = st.session_state.get("run_settings", {})
    rows, _ = apply_declarations(
        st.session_state.get("rows") or [],
        settings.get("declare_synthetic", False),
        settings.get("source_label"),
        settings.get("assign_missing_ids", False),
        settings.get("data_origin"),
    )
    if cfg.policy_terms["enabled"] and not rows:
        cfg = cfg.replace(policy_terms={**cfg.policy_terms, "enabled": False})
    ranges = uncertainty_ranges(report, rows, cfg)
    st.session_state["uncertainty"] = (key, ranges)
    return ranges


def ingestion_eval():
    import json

    path = runtime().data_dir.parent / "outputs" / "ingestion_eval.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def ylt(report=None):
    """Year-loss-table EP curves for the current result, cached per analysis and config."""
    from floodcat.exposure.validation import apply_declarations
    from floodcat.financial.ylt import ylt_for_report

    report = report or result()
    if report is None:
        return None
    cfg = config()
    key = (report["analysis_id"], cfg.fingerprint)
    cached = st.session_state.get("ylt")
    if cached and cached[0] == key:
        return cached[1]
    settings = st.session_state.get("run_settings", {})
    rows, _ = apply_declarations(
        st.session_state.get("rows") or [],
        settings.get("declare_synthetic", False),
        settings.get("source_label"),
        settings.get("assign_missing_ids", False),
        settings.get("data_origin"),
    )
    if cfg.policy_terms["enabled"] and not rows:
        cfg = cfg.replace(policy_terms={**cfg.policy_terms, "enabled": False})
    curves = ylt_for_report(report, rows, cfg)
    st.session_state["ylt"] = (key, curves)
    return curves


def rp_sentence(years, loss):
    return f"1-in-{years:,.0f} year loss: {kes(loss, compact=False)}"


def exposure_labels(report=None):
    """['REAL'], ['SYNTHETIC'] or both, from the run's actual data."""
    report = report or result()
    return list((report or {}).get("exposure_origin", {}).get("labels", ["SYNTHETIC"]))


def exposure_words(report=None):
    labels = exposure_labels(report)
    return (
        "real and synthetic properties"
        if len(labels) > 1
        else "real properties"
        if labels == ["REAL"]
        else "synthetic properties"
    )


def screen_upload(data, digest):
    """Malware scan and upload quota, once per file (SEC-04, SEC-05). Returns True when the file may be read."""
    done = st.session_state.setdefault("_screened", {})
    if digest in done:
        return done[digest] != "rejected"
    from floodcat.platform import orgs
    from floodcat.platform.scanning import scan

    try:
        with platform().tx() as conn:
            orgs.check_upload_quota(conn, principal())
            result = scan(data)
            from floodcat.platform import audit

            audit.record(
                conn,
                "file.uploaded",
                actor=principal(),
                target_type="file",
                target_id=digest[:16],
                details={"file_sha256": digest, "bytes": len(data), "scan": result},
                request=request_info(),
            )
        done[digest] = result
        st.caption(
            "Malware scan: "
            + (
                "clean"
                if result == "clean"
                else "scanner not configured (development only)"
            )
        )
        return True
    except ModelError as exc:
        done[digest] = "rejected"
        st.error(str(exc), icon=":material/gpp_bad:")
        return False


def ai_quota():
    """Check and count one AI request for this user and organisation. Returns False (with a message) when over quota."""
    from floodcat.platform.orgs import check_ai_quota

    try:
        with platform().tx() as conn:
            check_ai_quota(conn, principal())
        return True
    except ModelError as exc:
        st.error(str(exc), icon=":material/hourglass_top:")
        return False


def briefing_facts(report=None):
    from floodcat.ai.briefing import build_facts
    from floodcat.hazard.hotspots import hotspot_check

    report = report or result()
    review = st.session_state.get("submission_review")
    sub = (
        review
        if review and review.get("label") == st.session_state.get("run_label")
        else None
    )
    try:
        y, r = ylt(report), uncertainty(report)
    except ModelError:
        y = r = None
    return build_facts(
        report, y, r, hotspot_check(runtime().hotspots, runtime().hazard), sub
    )


def draft_briefing():
    """AI briefing from the fact pack; stored in the session for this analysis and audited."""
    from floodcat.ai.briefing import draft
    from floodcat.platform import audit

    report = result()
    if not ai_quota():
        return None
    facts = briefing_facts(report)
    try:
        briefing = draft(facts, llm(client_data=run_has_client_data(report)))
    except ModelError as exc:
        st.error(str(exc))
        return None
    with platform().tx() as conn:
        audit.record(
            conn,
            "ai.briefing_generated",
            actor=principal(),
            target_type="run",
            target_id=report["analysis_id"],
            details={
                "model": briefing["model"],
                "prompt_version": briefing["prompt_version"],
                "facts": len(facts),
                "unsupported_figures": briefing["unsupported_figures"],
            },
            request=request_info(),
        )
    st.session_state["briefing"] = {
        "analysis_id": report["analysis_id"],
        "briefing": briefing,
        "facts": facts,
    }
    return briefing


def current_briefing():
    b = st.session_state.get("briefing")
    report = result()
    return b if b and report and b["analysis_id"] == report["analysis_id"] else None


def people():
    """{user_id: display name} for the organisation's active members (for showing who did what)."""
    from sqlalchemy import select
    from floodcat.platform.db import memberships, users

    p = principal()
    if p is None or not p.org_id:
        return {}
    with platform().tx() as conn:
        return {
            r.id: r.display_name
            for r in conn.execute(
                select(users.c.id, users.c.display_name)
                .join(memberships, memberships.c.user_id == users.c.id)
                .where(
                    memberships.c.org_id == p.org_id, memberships.c.status == "active"
                )
            )
        }


# Infrastructure-deficit index ----------------------------------------------
def imd_available():
    """True when the IMD grid has been built (scripts/build_imd_index.py); the switch is disabled otherwise."""
    try:
        runtime().imd
        return True
    except ModelError:
        return False


@st.cache_data(show_spinner="Checking the index against the named flood areas…")
def imd_check(settings_json):
    """Hotspot hit rate and map share flagged, terrain only vs with the index, for these settings."""
    import json
    from floodcat.hazard.imd import Grid, area_comparison, hotspot_comparison

    rt = runtime()
    settings = rt.config.replace(imd_index=json.loads(settings_json)).imd_index
    array, transform, _, height, width = rt.hazard.grids["common"]
    return {
        "hotspots": hotspot_comparison(rt.hotspots, rt.hazard, rt.imd, settings),
        "map_area": area_comparison(array, Grid(transform.c, transform.f, transform.a, width, height), rt.imd, settings),
    }


def audit_ai(action, target_type, target_id, details):
    """Audit one AI action (model, prompt version, counts — never the text sent or received)."""
    from floodcat.platform import audit

    with platform().tx() as conn:
        audit.record(
            conn,
            action,
            actor=principal(),
            target_type=target_type,
            target_id=str(target_id)[:120],
            details={**details, "provider": st.session_state.get("ai_provider_used")},
            request=request_info(),
        )


def drainage_ready():
    return runtime().drainage_layers is not None


def org_evidence():
    """The organisation's evidence library (tenant-scoped)."""
    from floodcat.platform import data

    p = principal()
    if p is None or not p.org_id:
        return []
    with platform().tx() as conn:
        return [e for e, _ in data.list_evidence(conn, p.org_id)]
