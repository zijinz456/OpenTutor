# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

WORKDIR /app

# Runtime-only system deps (libpq for psycopg2, curl for healthcheck, docker CLI for sandbox)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -r opentutor && useradd -r -g opentutor -d /app -s /sbin/nologin opentutor \
    && mkdir -p /app/uploads && chown -R opentutor:opentutor /app

COPY --chown=opentutor:opentutor . .

USER opentutor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["bash", "-lc", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
