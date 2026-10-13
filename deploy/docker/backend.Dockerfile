# One image for api, processor, worker and migrate.
FROM python:3.12-slim-trixie

# gnupg: PGP forwards and backup encryption; postgresql-client-17: pg_dump for backups.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    LOG_DIR=/app/logs

WORKDIR /app
# Dependencies first so code changes reuse the cached layer.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev

# Same uid as the deploy user on the host, so bind-mounted log directories are writable.
ARG APP_UID=1000
RUN useradd --uid "${APP_UID}" --create-home app && mkdir -p /app/logs && chown app /app/logs
USER app

CMD ["uvicorn", "mailalias.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
