# syntax=docker/dockerfile:1.7-labs
###############################################################################
# Stage 1 — build SPA
###############################################################################
FROM node:20-alpine AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

###############################################################################
# Stage 2 — build python wheels
###############################################################################
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY apps ./apps
COPY packages ./packages
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -e .

###############################################################################
# Stage 3 — runtime
###############################################################################
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APIBANK_EMBED_WORKERS=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin apibank

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY apps ./apps
COPY packages ./packages
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY --from=web /web/dist ./apps/web/dist

USER apibank
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status==200 else 1)"

CMD ["apimb", "start", "--host", "0.0.0.0", "--port", "8000"]
