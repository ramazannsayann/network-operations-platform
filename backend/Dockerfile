# syntax=docker/dockerfile:1
# One image for the api, worker and scheduler services; each sets its own command.

# ---- build: install locked dependencies and the netops package into /app/.venv ----
FROM python:3.12-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so this layer stays cached until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---- runtime: no build tooling, runs as an unprivileged user ----
FROM python:3.12-slim-trixie
RUN groupadd --system --gid 10001 netops \
    && useradd --system --uid 10001 --gid netops --no-create-home netops
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER netops
EXPOSE 8000
# Proxy headers are trusted because the api is only reachable through nginx (or localhost).
CMD ["uvicorn", "netops.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
