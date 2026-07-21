# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

# Pinned uv for reproducible builds; bump deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependency files first for layer caching; cache mount keeps uv's wheel cache warm.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:3.14-slim AS runtime

# No system ffmpeg: moviepy uses the bundled imageio-ffmpeg binary.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Non-root runtime. UID/GID 1000 pairs with securityContext.fsGroup on the
# k8s deployment so the /data PVC stays writable.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --no-log-init --no-create-home --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY run_bot.py ./
COPY reverse_image_search_bot/ ./reverse_image_search_bot/

# 9004 webhook ingress, 9100 Prometheus metrics, 9200 abuse-report webview.
EXPOSE 9004 9100 9200

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/', timeout=4)"]

USER app

CMD ["python", "run_bot.py"]
