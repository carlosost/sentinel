# ---------------------------------------------------------------------------
# Sentinel — Autonomous SRE Incident Copilot — multi-stage Docker build
#
# Status (Feature 01, ADR-021): there is no HTTP API / app server yet — Open
# Question #10 (PROJECT_MEMORY.md §7) tracks designing that, planned around
# roadmap items 9-10. Until it exists, this image's default command runs a
# "smoke" check (import the package, build the graph, call the gateway/
# guardrail stubs) so `docker run` always does something meaningful instead
# of either pretending an API exists or just sitting idle. Override the
# command (`pytest`, `bash`, a future `uvicorn ...`) as needed — see
# scripts/entrypoint.sh and the Makefile.
#
# Runtime environment variables (set via infra/docker-compose.yml or -e flags):
#
#   LITELLM_PROXY_URL    base URL of the LiteLLM proxy (ADR-003). Required —
#                        src/gateway/client_factory.py raises GatewayConfigError
#                        without it. In compose, set to http://litellm:4000.
#   LITELLM_VIRTUAL_KEY  per-caller virtual key (ADR-018: sentinel-app /
#                        sentinel-eval / sentinel-dev). Optional in dev.
#
# ---------------------------------------------------------------------------
# Stage 1: dependency builder
#
# Installs all Python dependencies into an isolated prefix (/install) so the
# runtime image carries no pip cache or build toolchain.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# psycopg[binary] bundles its own libpq — no build toolchain strictly required,
# but sentence-transformers/torch pull in packages that sometimes need one.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: runtime image
#
# Lean image — no build tools, only the installed packages copied from Stage 1.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Non-root application user (security hardening).
RUN useradd --create-home --shell /bin/bash appuser

# Runtime-only system deps:
#   libpq5  — psycopg shared library, for pgvector/checkpointer access (ADR-002).
#   curl    — used by the Makefile's health-check / wait-gate once an API exists.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Pull the full Python package tree from the builder. Lands everything under
# /usr/local so the system Python picks it up with no PYTHONPATH tricks.
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source. The bind-mount (.:/app) in infra/docker-compose.yml
# shadows this at runtime for local development; the image stays self-contained
# for CI / anywhere without a bind-mount.
COPY . .

# Entrypoint lives outside /app so it is never shadowed by the bind-mount.
RUN cp /app/scripts/entrypoint.sh /entrypoint.sh && chmod +x /entrypoint.sh

RUN chown -R appuser:appuser /app

USER appuser

# Every module import goes through src/ (e.g. `from src.gateway import client_factory`).
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["smoke"]
