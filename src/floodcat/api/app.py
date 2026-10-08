"""HTTP API and authentication pages. Every /v1 call acts as a Principal from an API token or the session cookie."""

import os
from typing import Annotated
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from ..ai.evidence import Evidence
from ..core.constants import TIERS
from ..core.errors import ModelError, ReviewRequired
from ..exposure.validation import summarise_issues
from ..platform import data, identity, orgs
from ..platform.rbac import require
from ..platform.service import platform
from ..platform.web import SESSION_COOKIE, req_info, router as auth_router
from ..reporting.export import json_report, property_csv
from ..services.runtime import Runtime
from ..vulnerability.functions import matrix
from .schemas import (
    AnalysisRequest,
    ApprovalRequest,
    CSVAnalysisRequest,
    EvidenceRequest,
    ExtractionRequest,
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self' https:",
}


def create_app(runtime=None):
    rt = runtime or Runtime()
    app = FastAPI(
        title="Xpat API",
        version="0.4.0",
        description="Flood portfolio analysis; uncalibrated prototype",
        docs_url=None if os.getenv("FLOODCAT_ENV") == "production" else "/docs",
        redoc_url=None,
    )
    origins = [
        x.strip()
        for x in os.getenv("FLOODCAT_CORS_ORIGINS", "http://127.0.0.1:8501").split(",")
        if x.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=True,
    )

    @app.middleware("http")
    async def headers(request, call_next):
        identity.use_request_host(request.url.hostname)
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.scheme == "https" or os.getenv("FLOODCAT_ENV") == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def home():
        """The auth server's root has nothing to show; send people to the app."""
        from fastapi.responses import RedirectResponse

        return RedirectResponse(identity.app_url(), status_code=307)

    @app.exception_handler(ModelError)
    async def model_error(request, exc):
        body = {"code": exc.code, "message": str(exc)}
        if isinstance(exc, ReviewRequired):
            body["issues"] = summarise_issues(exc.issues)
        status = {
            "not_found": 404,
            "forbidden": 403,
            "unauthenticated": 401,
            "rate_limited": 429,
        }.get(exc.code, 422)
        return JSONResponse(status_code=status, content=body)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):  # SEC-11: no stack traces to clients
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Something went wrong. The error was logged.",
            },
        )

    app.include_router(auth_router)

    def principal(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ):
        with platform().tx() as conn:
            if authorization and authorization.lower().startswith("bearer "):
                identity.rate_limit(
                    conn,
                    f"api-ip:{req_info(request)['ip']}",
                    600,
                    identity.timedelta(minutes=1),
                    "API rate limit exceeded",
                )
                p = identity.resolve_api_token(
                    conn, authorization.split(" ", 1)[1].strip(), req_info(request)
                )
            else:
                p, _ = identity.resolve_session(
                    conn, request.cookies.get(SESSION_COOKIE)
                )
        if p is None:
            raise HTTPException(
                401, "Sign in or send a valid API token (Authorization: Bearer xpat_…)"
            )
        return p

    def allowed(p, permission):
        if not identity.token_allows(p, permission):
            raise ModelError("forbidden", f"Not permitted: {permission}")

    def org_config(p, overrides=None):
        with platform().tx() as conn:
            base = data.house_config(conn, p.org_id)
        from ..core.config import ModelConfig

        return ModelConfig(**{**base, **(overrides or {})})

    @app.get("/health")
    def health():
        from ..ai.llm import available

        with platform().tx() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {
            "status": "ok",
            "ai_available": available(),
            "database": platform().engine.dialect.name,
        }

    @app.get("/v1/me")
    def me(p=Depends(principal)):
        return {
            "user_id": p.user_id,
            "email": p.email,
            "org_id": p.org_id,
            "roles": list(p.roles),
            "scopes": list(p.extra.get("token_scopes") or []),
        }

    @app.get("/v1/model")
    def metadata(p=Depends(principal)):
        cfg = org_config(p)
        return {"config": cfg.to_dict(), "vulnerability_matrix": matrix(cfg)}

    @app.post("/v1/analyses", status_code=201)
    def new_analysis(body: AnalysisRequest, request: Request, p=Depends(principal)):
        allowed(p, "runs.create")
        with platform().tx() as conn:
            if not orgs.flag_enabled(conn, p.org_id, "api_access"):
                raise ModelError(
                    "forbidden", "API access is disabled for this organisation"
                )
            evidence = (
                [e for e, _ in data.list_evidence(conn, p.org_id)]
                if body.ai_adjustment
                else None
            )
        result = rt.run(
            body.rows,
            config=org_config(p, body.config),
            declare_synthetic=body.declare_synthetic,
            data_origin=body.data_origin,
            allow_partial=body.allow_partial,
            ai_adjustment=body.ai_adjustment,
            evidence=evidence,
        )
        with platform().tx() as conn:
            data.save_run(
                conn,
                p,
                result,
                body.rows,
                "API run",
                {"data_origin": body.data_origin},
                visibility=body.visibility,
                request=req_info(request),
            )
        return result

    @app.post("/v1/analyses/csv", status_code=201)
    def csv_analysis(body: CSVAnalysisRequest, request: Request, p=Depends(principal)):
        return new_analysis(
            AnalysisRequest(
                rows=rt.parse_upload(body.csv_text),
                allow_partial=body.allow_partial,
                declare_synthetic=body.declare_synthetic,
                data_origin=body.data_origin,
                ai_adjustment=body.ai_adjustment,
                config=body.config,
                visibility=body.visibility,
            ),
            request,
            p,
        )

    @app.get("/v1/analyses")
    def list_analyses(p=Depends(principal)):
        allowed(p, "runs.read")
        with platform().tx() as conn:
            return data.list_runs(conn, p)

    @app.get("/v1/analyses/{identifier}")
    def get_analysis(identifier: str, request: Request, p=Depends(principal)):
        allowed(p, "runs.read")
        with platform().tx() as conn:
            return data.get_run(conn, p, identifier, request=req_info(request))[
                "payload"
            ]

    @app.get("/v1/analyses/{identifier}/export")
    def export(
        identifier: str,
        request: Request,
        format: str = "json",
        run: str = "baseline",
        tier: str = "common",
        p=Depends(principal),
    ):
        allowed(p, "runs.export")
        with platform().tx() as conn:
            result = data.get_run(conn, p, identifier)["payload"]
            if format == "json":
                data.record_export(conn, p, identifier, "json", req_info(request))
                return Response(
                    json_report(result),
                    media_type="application/json",
                    headers={
                        "Content-Disposition": 'attachment; filename="risk-report.json"'
                    },
                )
            if format != "csv" or run not in result["runs"] or tier not in TIERS:
                raise ModelError(
                    "invalid_export",
                    "Use json or csv with an available run and valid tier",
                )
            data.record_export(conn, p, identifier, "csv", req_info(request))
        return Response(
            property_csv(result, run, tier),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="property-losses.csv"'
            },
        )

    @app.post("/v1/evidence", status_code=201)
    def add_evidence(body: EvidenceRequest, request: Request, p=Depends(principal)):
        allowed(p, "evidence.add")
        item = Evidence(**body.model_dump())
        with platform().tx() as conn:
            data.add_evidence(conn, p, item, req_info(request))
        return item.to_dict()

    @app.get("/v1/evidence")
    def list_evidence(p=Depends(principal)):
        allowed(p, "runs.read")
        with platform().tx() as conn:
            return [e.to_dict() for e, _ in data.list_evidence(conn, p.org_id)]

    @app.post("/v1/evidence/{identifier}/approve")
    def approve(identifier: str, request: Request, p=Depends(principal)):
        allowed(p, "evidence.approve")
        with platform().tx() as conn:
            return data.approve_evidence(
                conn, p, identifier, req_info(request)
            ).to_dict()

    @app.post("/v1/evidence/extract")
    def extract(body: ExtractionRequest, p=Depends(principal)):
        allowed(p, "ai.extract")
        with platform().tx() as conn:
            settings = identity.settings_for(conn, p.org_id)
            if settings["ai_mode"] != "full":
                raise ModelError(
                    "forbidden", "AI evidence extraction is off for this organisation"
                )
        from ..ai.extraction import extract as run_extraction
        from ..ai.llm import choose

        client = rt.llm(
            choose(settings, p.user_id, client_data=False)[0]
        )  # published reports, not client data
        return run_extraction(body.text, body.source, client, rt.gazetteer(llm=client))

    return app
