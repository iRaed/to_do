FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Non-root user
RUN useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot

# Default to paper-trading loop. The .env file is mounted at runtime; secrets
# never enter the image.
CMD ["python", "-m", "app.main", "run"]
