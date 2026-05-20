FROM python:3.14-slim AS builder

# Build deps: git required for moviepy git dependency
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.14-slim

# Runtime deps: ffmpeg required by moviepy for video frame extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pull the venv from builder — no build tools in the final image
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source
COPY run_bot.py ./
COPY reverse_image_search_bot/ ./reverse_image_search_bot/

CMD ["python", "run_bot.py"]
