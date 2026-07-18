# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

# No system build deps needed — all wheels are prebuilt (moviepy's git dep,
# which required git, was dropped in favour of imageio-ffmpeg).

# Pinned uv (reproducible builds — :latest drifts). Bump deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

# uv best practice: compile bytecode at build time, copy (not hardlink) across
# the mount boundary, never fetch a managed Python — use the image's.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Copy dependency files first for better layer caching.
# Cache mount keeps uv's wheel cache warm across rebuilds without bloating layers.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:3.14-slim AS runtime

# NOTE: no system ffmpeg. moviepy resolves to the imageio-ffmpeg bundled binary
# (verified: FFMPEG_BINARY -> .venv/.../imageio_ffmpeg/binaries/ffmpeg-*), and
# nothing in the app shells out to /usr/bin/ffmpeg. apt ffmpeg would be dead weight.

# Unbuffered stdout so logs reach k8s immediately; no stray .pyc at runtime
# (bytecode is already compiled into the venv at build time).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Non-root runtime. UID/GID 1000 pairs with `securityContext.fsGroup: 1000`
# on the k8s deployment so the /data PVC stays writable.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --no-log-init --no-create-home --home-dir /app app

WORKDIR /app

# Pull the venv from builder — no build tools in the final image
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY run_bot.py ./
COPY reverse_image_search_bot/ ./reverse_image_search_bot/

# Documented service ports: 9004 webhook ingress, 9100 Prometheus metrics,
# 9200 abuse-report webview (aiohttp). Metadata only — k8s maps them explicitly.
EXPOSE 9004 9100 9200

# Local/compose liveness: metrics server is on by default (METRICS_ENABLED).
# k8s ignores this and uses its own probes — see deployment.yaml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/', timeout=4)"]

USER app

CMD ["python", "run_bot.py"]
