FROM python:3.11-slim

# ffmpeg is required by moviepy for video frame extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install poetry and disable venv creation (we're already isolated in a container)
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false

# Copy dependency files first for better layer caching
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --no-ansi --without dev

# Copy application source
COPY run_bot.py ./
COPY reverse_image_search_bot/ ./reverse_image_search_bot/

CMD ["python", "run_bot.py"]
