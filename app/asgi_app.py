"""Xpat on one address: the Streamlit interface plus the sign-in pages and API, served by one server.

`scripts/run_app.py` starts this by default (`streamlit run app/asgi_app.py`), so the browser only ever sees
http://127.0.0.1:8501. Streamlit owns the root and its pages; requests under /auth (sign-in, registration, two-step,
password reset), /v1 (the API), /health and the API docs are handed, with their full paths, to the same FastAPI app
that otherwise runs on port 8000 (`floodcat.api.app:create_app`). The session cookie it sets is then read by the
interface on the same host and port.

In production a reverse proxy does the same job in front of two servers (see README, Production).
"""

import os
from pathlib import Path
import streamlit as st
from starlette.routing import Route

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Read .env first (without overriding the environment), as the interface script does, so the API sees the same settings.
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
# Sign-in links and redirects point at this same server.
os.environ.setdefault("FLOODCAT_AUTH_PORT", os.environ.get("FLOODCAT_APP_PORT", "8501"))

from floodcat.api.app import create_app  # noqa: E402  (after the settings above)

API_PATHS = (
    "/auth",
    "/auth/{rest:path}",
    "/v1/{rest:path}",
    "/health",
    "/docs",
    "/openapi.json",
)
api = create_app()

# `streamlit run` finds the server by reading this file for a top-level `app = st.App(...)`, so keep that exact form.
app = st.App(
    str(HERE / "streamlit_app.py"), routes=[Route(path, api) for path in API_PATHS]
)
