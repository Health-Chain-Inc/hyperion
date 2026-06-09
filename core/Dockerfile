# hyperion-core — FHIR R4 → relational SQL pipeline image.
# Dispatches by APPLICATION_NAME env var via entrypoint.sh.
# Default APPLICATION_NAME=core-data-ingester runs the pipeline; other values
# run the sidecar modules (admin_grant_manager, root_password_manager, etc.).
FROM python:3.11-slim-bookworm

ENV APP_BASE_DIR=/opt/app \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Minimal system deps (HTTPS + CA bundle for outbound TLS to Azure / FHIR)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

# === Non-root user (uid/gid 1000 for compliance scanning) ===
RUN groupadd -g 1000 hyperion && \
    useradd -u 1000 -g hyperion -m -s /bin/bash hyperion && \
    mkdir -p ${APP_BASE_DIR} && \
    chown -R hyperion:hyperion ${APP_BASE_DIR}

WORKDIR ${APP_BASE_DIR}
USER hyperion

# Python dependencies
COPY --chown=hyperion:hyperion requirements.txt .
RUN pip install --no-cache-dir --upgrade pip protobuf && \
    pip install --no-cache-dir -r requirements.txt

# Entrypoint
COPY --chown=hyperion:hyperion entrypoint.sh /entrypoint.sh
USER root
RUN chmod +x /entrypoint.sh
USER hyperion

# Application code
COPY --chown=hyperion:hyperion . .

ENTRYPOINT ["/entrypoint.sh"]
