FROM python:3.11-slim AS builder

# Build deps: C compiler + Kerberos headers (required by gssapi C extension)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libkrb5-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false

# Copy dependency files first for better layer caching
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --no-ansi --without dev


FROM python:3.11-slim

# Runtime deps only:
#   ffmpeg          — required by moviepy for video frame extraction
#   libgssapi-krb5-2 — runtime .so that the compiled gssapi extension links against
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pull installed packages from builder — no build tools in the final image
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application source
COPY run_bot.py ./
COPY reverse_image_search_bot/ ./reverse_image_search_bot/

CMD ["python", "run_bot.py"]
