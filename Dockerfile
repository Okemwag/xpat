FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN uv sync --locked --no-dev --extra geo && useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD [".venv/bin/uvicorn", "floodcat.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
