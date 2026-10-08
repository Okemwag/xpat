FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY configs ./configs
COPY app ./app
COPY .streamlit ./.streamlit
COPY outputs/ingestion_eval.json ./outputs/ingestion_eval.json
COPY logo.png ./logo.png
RUN uv sync --locked --no-dev --extra geo --extra ui --extra ai && useradd --create-home appuser && mkdir -p /app/runtime/store && chown -R appuser /app/runtime
USER appuser
EXPOSE 8000 8501
# Default: the sign-in/API server. The interface service overrides the command (see compose.yaml).
CMD [".venv/bin/uvicorn", "floodcat.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
