# ---- Stage 1: Builder ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY config/*.example ./config/
RUN uv sync --frozen --no-dev

# ---- Stage 2: Runtime ----
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
ENV TIKTOK_RECORDER_CONFIG_DIR=/app/config

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r recorder && useradd -r -g recorder -d /app recorder

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/config /app/config
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh && \
    chown -R recorder:recorder /app

USER recorder

ENTRYPOINT ["/app/entrypoint.sh"]
