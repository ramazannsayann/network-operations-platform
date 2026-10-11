# syntax=docker/dockerfile:1
# One image for the api, worker and scheduler services; each sets its own command.
# The last stage (runtime) is the default target; `fakelab` builds the fake devices.

# Registry of the base images: Docker Hub by default. CI pulls the same images (identical
# digests) through mirror.gcr.io, Google's Docker Hub mirror, because shared CI runners hit
# Docker Hub's anonymous pull rate limit.
ARG BASE_REGISTRY=docker.io

# ---- build: install locked dependencies and the netops package into /app/.venv ----
FROM ${BASE_REGISTRY}/library/python:3.12-slim-trixie AS build
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

# ---- fakelab: the fake SSH devices of the fake lab (deploy/docker-compose.fakelab.yml) ----
# Same package plus the optional "fakelab" extra (asyncssh). Not part of the platform.
FROM build AS build-fakelab
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra fakelab

FROM ${BASE_REGISTRY}/library/python:3.12-slim-trixie AS fakelab
# /lab/state: the shared state volume (changes applied by make fakelab-change); a new
# named volume takes this directory's owner.
RUN groupadd --system --gid 10001 netops \
    && useradd --system --uid 10001 --gid netops --no-create-home netops \
    && install -d -o netops -g netops /lab/state
COPY --from=build-fakelab /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER netops
ENTRYPOINT ["python", "-m", "netops_fakes.serve"]

# ---- runtime: no build tooling, runs as an unprivileged user (the default target) ----
FROM ${BASE_REGISTRY}/library/python:3.12-slim-trixie AS runtime
# /var/lib/netops/configs: the configuration repository (ADR-0007), a volume of its own;
# complete configurations with secrets, so only the netops user may enter it.
RUN groupadd --system --gid 10001 netops \
    && useradd --system --uid 10001 --gid netops --no-create-home netops \
    && install -d -m 0700 -o netops -g netops /var/lib/netops/configs
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
