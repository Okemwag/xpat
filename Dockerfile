FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir runtime && chown appuser runtime
USER appuser
EXPOSE 8000
CMD ["uvicorn", "floodcat.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
