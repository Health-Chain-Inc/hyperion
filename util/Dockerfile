# hyperion-util — one-shot bootstrap for the Hyperion engine.
# Runs `python main.py`, creates storage volume + core/audit DBs + FHIR
# tables + service account, exits 0. Safe to re-run (idempotent).
FROM python:3.11-slim-bookworm

ENV APP_BASE_DIR=/app \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Minimal system deps (HTTPS + recent CA bundle for outbound TLS)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -g 1000 hyperion && \
    useradd -u 1000 -g hyperion -m -s /bin/bash hyperion && \
    mkdir -p ${APP_BASE_DIR} && \
    chown -R hyperion:hyperion ${APP_BASE_DIR}

WORKDIR ${APP_BASE_DIR}
USER hyperion

# Python dependencies
COPY --chown=hyperion:hyperion requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=hyperion:hyperion . .

CMD ["python", "main.py", "bootstrap"]