# Azure deployment

The OSS release ships a second compose file (`docker-compose.azure.yml`) for deploying Hyperion against Azure-managed FHIR, Service Bus, and Blob Storage. It's a **hybrid topology**: the Hyperion Engine runs locally in containers, but every other Hyperion dependency comes from Azure. This is the natural eval / PoC / small-scale pattern; see [Going to production](#going-to-production) for graduating to a managed engine cluster.

---

## Prerequisites

This compose deploys Hyperion. It does **not** provision Azure resources; bring those up first via your usual IaC (Bicep, Terraform, Azure Portal, etc.).

| Azure resource | What's needed | Maps to env vars |
|---|---|---|
| **Azure Health Data Services FHIR** | An endpoint with the data you want to ingest, plus a service principal with read access | `AZURE_FHIR_SERVER_BASEURL`, `AZURE_FHIR_SERVER_CLIENT_ID`, `AZURE_FHIR_SERVER_CLIENT_SECRET`, `AZURE_FHIR_SERVER_TOKEN_URL`, `AZURE_FHIR_SERVER_SCOPE` |
| **Azure Service Bus namespace** | Four queues: `event`, `batch`, `retry`, `audit` (full names in [`../core/README.md`](../core/README.md)) | `AZURE_SERVICEBUS_NAMESPACE_CONNECTION_STRING`, `AZURE_SERVICEBUS_*_QUEUE` |
| **Azure Blob Storage account** | Containers for table data, NDJSON staging, and failure NDJSON | `AZURE_BLOB_STORAGE_SILVER_LAYER_CONTAINER`, `AZURE_STORAGE_CONTAINER_STAGE`, `AZURE_STORAGE_CONTAINER_FAILURE`, `AZURE_STORAGE_ACCOUNT_CONNECTION_STRING` |
| **(Optional) Managed engine cluster** | Only if going straight to production; the default compose runs the engine locally | `SILVER_LAYER_QUERY_SERVER`, `SILVER_LAYER_HTTP_SERVER` |

The full env reference is in [`configuration.md`](configuration.md).

---

## One-shot deployment

```bash
cp .env.example .env
# In .env:
#   1. Set the three switches:
#        FHIR_SERVICE=azure
#        CLOUD_STORAGE=azure
#        SERVICEBUS=azure
#   2. Uncomment the AZURE_* block at the bottom and fill in:
#        - AZURE_FHIR_SERVER_*       (Azure Health Data Services credentials)
#        - AZURE_SERVICEBUS_*        (Service Bus connection + queue names)
#        - AZURE_STORAGE_*           (Blob Storage account + containers)
#        - AZURE_BLOB_STORAGE_*      (table-data container + endpoint + version)
#   3. AZURE_BLOB_STORAGE_VERSION:
#        - 1 for Azure Blob (gen1)  -> engine uses TYPE=AZBLOB
#        - 2 for ADLS Gen2          -> engine uses TYPE=ADLS2
#      Both util and the engine read this single env var.

# --build builds the local Hyperion images (util + core) before starting. Without
# it, the six core processors try to pull hyperion/core:local from a registry and
# fail. The images are built from source, not published anywhere.
docker compose -f docker-compose.azure.yml up --build
```

---

## What comes up

In dependency order:

| Service | Role | Exits |
|---|---|---|
| `starrocks-fe` | Engine frontend in shared-data mode; storage volume points at your Azure Blob | (long-running) |
| `starrocks-cn` | Engine compute node, FQDN-advertised | (long-running) |
| `hyperion-util` | One-shot bootstrap: storage volume, `_hyperion_core_`, `_hyperion_audit_`, FHIR resource tables, service account | bootstrap done |
| `core-data-ingester` | Consumes the batch queue, downloads NDJSON from Blob, normalizes, stream-loads | (long-running) |
| `batch-load-exporter` | Pulls FHIR resources for a time window, stages NDJSON to Blob, enqueues ingester work | (long-running) |
| `event-load-exporter` | Consumes per-resource change events from FHIR, stages NDJSON | (long-running) |
| `batch-scheduler` | Reads catch-up windows from `_hyperion_audit_`, schedules batch-load runs | (long-running) |
| `audit-lineage-manager` | Drains the audit queue, stream-loads audit + lineage rows to the engine | (long-running) |
| `retry-manager` | Handles 602 / 603 retry codes: re-stages failed NDJSON and re-enqueues | (long-running) |

All six application processors run the same `hyperion/core:local` image and differ only in `APPLICATION_NAME`. This mirrors a recommended Kubernetes topology (one pod per processor) collapsed to a single host.

---

## Verification

After util-bootstrap exits 0 and core processors are running:

```bash
# Engine has the FHIR-shaped schema
docker exec -it hyperion-starrocks-fe \
  mysql -h 127.0.0.1 -P 9030 -u root \
  -e "USE _hyperion_core_; SHOW TABLES;"

# Pipeline is reading from your Azure FHIR: check audit DB for activity
docker exec -it hyperion-starrocks-fe \
  mysql -h 127.0.0.1 -P 9030 -u root \
  -e "USE _hyperion_audit_;
      SELECT * FROM pipeline_meta_info ORDER BY updated_date DESC LIMIT 10;
      SELECT count(*) AS audit_rows FROM fhir_audit;"
```

Rows in `fhir_audit` confirm core is pulling from Azure FHIR and recording activity. The first batch may take a few minutes after `up` to appear, depending on Service Bus queue depth and Azure FHIR response time.

---

## Tearing down

```bash
docker compose -f docker-compose.azure.yml down
```

Drops the local engine containers but does **not** touch your Azure-side data (table data in Blob Storage, queues, FHIR data). Restarting via `up` reconnects to the same Azure resources.

---

## Going to production

The hybrid compose runs the Hyperion Engine in two Docker containers: fine for evaluation, PoC, and small-scale workloads. For a managed cluster (recommended for any real workload), two small changes:

**1. In `docker-compose.azure.yml`**: comment out (or delete) the `starrocks-fe` and `starrocks-cn` services, and remove the `depends_on` entries that reference them from `hyperion-util` and the six core processors (keep the core processors' dependency on `hyperion-util`).

**2. In `.env`**: point engine endpoints at your managed cluster:

```ini
SILVER_LAYER_QUERY_SERVER=<your-cluster-host>:9030
SILVER_LAYER_HTTP_SERVER=<your-cluster-host>:8030
SILVER_LAYER_ROOT_PASSWORD=<your-root-password>
```

Re-run `docker compose -f docker-compose.azure.yml up --build`. Only util + the six core processors come up; they connect to your external engine cluster.

For full Kubernetes deployments (each `APPLICATION_NAME` as its own Deployment, secrets via Key Vault, horizontal autoscaling), see [`../core/README.md`](../core/README.md) under *Production deployment notes*. **Helm charts and Terraform are intentionally not included** in this OSS release. Operators bring their own.

---

## Re-enabling sidecars

Three sidecars (`admin-grant-manager`, `root-password-manager`, `cluster-metadata-exporter`) are omitted from the Azure compose by default: they need a shared filesystem mount to the engine FE pod (to tail audit logs, rotate the root password, back up FE metadata), which doesn't fit a single-container engine. To run them on Kubernetes against a real FE pod, see the sidecar block in [`../core/.env.example`](../core/.env.example) and *Production deployment notes* in [`../core/README.md`](../core/README.md).
