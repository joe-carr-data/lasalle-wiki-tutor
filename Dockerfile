# LaSalle Wiki Tutor — production image.
#
# Three-stage build:
#   1. frontend-build  — Node 22, builds the Vite/React bundle to /app/frontend/dist
#   2. python-deps     — uv-based Python 3.13 image, resolves and installs deps into /app/.venv
#   3. runtime         — slim Python 3.13, copies the venv + bundled frontend + app code
#
# Required at the build context (NOT created by this Dockerfile):
#
#   wiki/                — the rendered Markdown corpus the agent reads from.
#                          Regenerate locally with `uv run python scripts/build_wiki.py`
#                          before `docker build`. It is .gitignored on purpose
#                          (large, easily reproducible) but must exist here.
#
# Runtime environment (pass via `docker run -e`, compose `environment`, or an
# `--env-file`):
#
#   OPENAI_API_KEY            required — agent calls OpenAI Responses API
#   WIKI_TUTOR_ACCESS_TOKEN   required for any non-localhost deploy — see core/auth.py
#   MONGO_URL                 default mongodb://mongo:27017 (compose service name)
#   MONGO_DATABASE            default lasalle_catalog_assistant
#   ENVIRONMENT               default local; set to dev or prod as appropriate
#   ASSISTANT_NAME            default "LaSalle Wiki Tutor"
#
# Healthcheck: GET /health returns 200 once uvicorn is up. CMD listens on 0.0.0.0:8000.

# ─── Stage 1: frontend ──────────────────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend

# Cache `npm ci` on package files alone — code edits below don't bust this layer.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Build the bundle. tsc -b runs first (configured in package.json) so a type
# error fails the image build instead of shipping a half-broken UI.
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Python deps ───────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-deps
WORKDIR /app

# uv tuning for container builds: copy instead of hardlink (the cache and the
# venv often live on different filesystems in CI/CD), and pre-compile bytecode
# so first-import latency in the runtime stage is negligible.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first (without the project) so editing app code doesn't
# bust the heaviest layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Now bring in the project source and finalize the install. The packages
# listed in `[tool.hatch.build.targets.wheel].packages` get installed into
# the venv; the top-level app modules (streaming.py, etc.) are imported from
# the working directory at runtime.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Drop the local source-tree node_modules / dist so the runtime stage
# inherits the freshly-built frontend from stage 1, not whatever happened
# to be on the dev box.
RUN rm -rf /app/frontend/node_modules /app/frontend/dist

# ─── Stage 3: runtime ───────────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS runtime

# Run as a non-root user. UID 1000 matches a typical EC2 ec2-user/ubuntu so
# bind-mounted volumes don't end up root-owned.
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --create-home app

WORKDIR /app

# Bring in the resolved venv and the application source.
COPY --from=python-deps --chown=app:app /app /app

# Replace the (empty) frontend/dist with the just-built bundle from stage 1.
COPY --from=frontend-build --chown=app:app /app/frontend/dist /app/frontend/dist

# Put the venv on PATH so `uvicorn` resolves without `uv run`.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default to the compose service name; override with -e MONGO_URL=...
    MONGO_URL=mongodb://mongo:27017 \
    MONGO_DATABASE=lasalle_catalog_assistant \
    ENVIRONMENT=local

USER app
EXPOSE 8000

# Container-level health probe. Use the bundled `python` (no curl in slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else sys.exit(1)"

CMD ["uvicorn", "streaming:app", "--host", "0.0.0.0", "--port", "8000"]
