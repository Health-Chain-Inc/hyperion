# hyperion-core

**FHIR R4 → relational SQL ingestion pipeline for the Hyperion Engine (StarRocks).**

Hyperion Core pulls FHIR R4 resources from any FHIR-compliant server, normalizes the JSON into a flattened relational schema, and stream-loads the result into the Hyperion Engine (a StarRocks-based columnar database). The schema itself is derived from the FHIR JSON Schema (not hand-written column lists) so it stays current as FHIR evolves. Adding a new resource type is a config change, not a code change.

This repository is the **pipeline**. Its sibling `hyperion-util` bootstraps the engine schema (databases, tables, common-table DDL) before this pipeline runs. The two are meant to be cloned and run together; the parent mono-repo's `docker-compose.yml` orchestrates a complete local demo in one command.

---

## Table of contents

1. [Architecture at a glance](#architecture-at-a-glance)
2. [The local vs Azure mode switches](#the-local-vs-azure-mode-switches)
3. [Quick start](#quick-start)
4. [Modules: what `APPLICATION_NAME` can be](#modules--what-application_name-can-be)
5. [Repository layout](#repository-layout)
6. [Configuration via `.env`](#configuration-via-env)
7. [Building and running with Docker](#building-and-running-with-docker)
8. [Running tests](#running-tests)
9. [Production deployment notes](#production-deployment-notes)
10. [Contributing](#contributing)
11. [License](#license)

---

## Architecture at a glance

```
                                  +-----------------------------+
                                  |       hyperion-core         |
                                  |  (this repo, the pipeline)  |
                                  |                             |
   FHIR R4 server  -- fetch -->   |  fhir_clients               |
   (HAPI / Azure FHIR / etc.)     |       |                     |
                                  |       v                     |
                                  |  normalizer  (FHIR JSON     |
                                  |     |          Schema →     |
                                  |     v          tabular)     |
                                  |  transaction_manager        |
                                  +-----------+-----------------+
                                              |
                                              v stream-load (HTTP)
                                  +-----------------------------+
                                  |     Hyperion Engine         |
                                  |     (StarRocks)             |
                                  |  _hyperion_core_.*          |
                                  |  _hyperion_audit_.*         |
                                  +-----------------------------+
```

There are two operating modes:

- **Azure mode**: queue-driven. An exporter pulls FHIR resources for a time window, stages NDJSON to Azure Blob Storage, and enqueues work on Azure Service Bus. A separate ingester (the `core-data-ingester`) consumes the queue, downloads the staged NDJSON, normalizes, and stream-loads to the engine. Retry, audit, and lineage all run as independent processors.
- **Local (development)**: no queue, no blob. `core-data-ingester` pulls directly from HAPI FHIR, normalizes in-process, and stream-loads to the engine. The exporter / retry / scheduler modules aren't needed in this mode.

The algorithm centerpiece is `pyfiles/hyperion_core/normalizer.py`. It walks the FHIR JSON Schema, classifies every column (primitive / extension / `CodeableConcept` / `Reference` / `Identifier` / backbone), and factors the three repeating complex types into shared tables so they aren't denormalized per resource. New FHIR resources are handled without code changes. They pick up the same flattening rules from the schema.

---

## The local vs Azure mode switches

Three independent env vars control which cloud each subsystem uses. Each accepts `azure` or `local`.

| Env var | `local` behavior | `azure` behavior |
|---|---|---|
| `FHIR_SERVICE` | Instantiates `HapiFhirClient` against `FHIR_SERVER_URL` (HAPI). | Instantiates `AzureFHIRClient` against Azure Health Data Services FHIR. |
| `CLOUD_STORAGE` | **No storage client is instantiated.** Pipeline skips blob staging. | Instantiates `AzureStorageClient` for NDJSON staging + failure container. |
| `SERVICEBUS` | **No queue client is instantiated.** Pipeline skips the queue. | Instantiates `AzureQueueClient` for event / batch / retry / audit queues. |

The behavioral fork lives in `main.py:114`: when both `queue_client` and `storage_client` are `None`, `local_converter()` runs instead of `fhir_converter()`. Both paths share the same `Normalizer` and the same stream-load mechanics; only the fetch and staging layers differ.

Common combinations:

| `FHIR_SERVICE` | `CLOUD_STORAGE` | `SERVICEBUS` | What this is |
|---|---|---|---|
| `local` | `local` | `local` | Full local demo. Pulls from HAPI, no queue/blob. |
| `azure` | `azure` | `azure` | Full Azure mode. Queue-driven. |
| `azure` | `local` | `local` | Quick smoke test against a real Azure FHIR with no queue. Supported but not the canonical path. |

Mixed modes beyond these three are not regularly exercised; if you try one, expect to wire your own emulators.

---

## Quick start

### Option A: Full local demo (recommended)

If you've cloned the parent mono-repo (which includes `hyperion-core` and `hyperion-util` as siblings), the one-command demo lives at the repo root:

```bash
cd <mono-repo-root>
cp .env.example .env       # edit if you want to point at Azure
docker compose up --build
```

That brings up:

- **engine**: StarRocks 3.4 (the Hyperion Engine), MySQL protocol on `:9030`, HTTP stream-load on `:8030`.
- **minio**: S3-compatible storage backing the engine's shared-data volume.
- **hyperion-util**: one-shot container that creates `_hyperion_core_`, `_hyperion_audit_`, common tables, and per-resource tables.
- **hapi-fhir**: public HAPI FHIR JPA server, the FHIR data source.
- **hyperion-core**: this pipeline, configured for local mode by default.

After roughly 90 seconds the stack is ready. Connect any MySQL-protocol client (DBeaver, `mysql` CLI, etc.) to `localhost:9030` and query:

```sql
SELECT count(*) FROM _hyperion_core_.Patient;
```

### Option B: Build just this image (app developers)

Use this when you're developing the pipeline code itself and want to point at an engine + FHIR you already have running:

```bash
git clone https://github.com/Health-Chain-Inc/hyperion.git
cd hyperion/core
cp .env.example .env       # edit SILVER_LAYER_QUERY_SERVER, FHIR_SERVER_URL, etc.
docker build -t hyperion/core:local .
docker run --env-file .env hyperion/core:local
```

The image dispatches by `APPLICATION_NAME`. Default is `core-data-ingester` (the pipeline). To run a sidecar or one of the other processors, override the variable. See the next section.

#### Joining the hyperion-util local stack

If your engine + HAPI are running in `hyperion-util`'s local compose stack (`docker-compose.local-minio.yml`), the core container needs to join that Docker network; the default service names (`starrocks-fe`, `hapi-fhir`) only resolve inside it:

```bash
docker run --env-file .env --network util_default hyperion/core:local
```

The network name follows Docker Compose's convention: `<project-name>_default`, where project-name is the directory name (`util/`) unless overridden. Confirm with `docker network ls` if `util_default` doesn't show up.

---

## Modules: what `APPLICATION_NAME` can be

`main.py` reads `APPLICATION_NAME` and instantiates the matching processor. The three sidecars listed at the bottom are dispatched directly by `entrypoint.sh` and bypass `main.py`. They have their own scripts.

| `APPLICATION_NAME` | Module | What it does | Required clients (Azure mode) |
|---|---|---|---|
| `core-data-ingester` | `CoreLoadProcessor` | Main pipeline. Consumes queue messages, downloads NDJSON, normalizes, stream-loads. In **local mode**, pulls directly from HAPI instead. | storage, queue, fhir, core_db |
| `batch-load-exporter` | `FHIRBatchProcessor` | Pulls a FHIR resource type for a `[start, end]` window, stages NDJSON to blob, enqueues ingester work. | storage, queue, fhir |
| `event-load-exporter` | `FHIREventProcessor` | Consumes per-resource change events from FHIR and stages them as NDJSON. | storage, queue, fhir |
| `batch-scheduler` | `FHIRScheduler` | Reads catch-up windows from `_hyperion_audit_`, schedules batch-load runs. | queue, audit_db |
| `audit-lineage-manager` | `AuditLineageManager` | Drains the audit queue, stream-loads audit + lineage rows to the engine. | queue |
| `retry-manager` | `RetryManager` | Handles 602 / 603 retry codes. Re-stages failed NDJSON and re-enqueues. | storage, queue |
| `admin-grant-manager` | sidecar (`admin_grant_manager.py`) | Watches the FE audit log for `CREATE DATABASE` events, auto-grants the admin role. | engine FE shared volume |
| `root-password-manager` | sidecar (`root_password_manager.py`) | Rotates the engine root password on a cron, stores it to a sealed blob. | engine FE shared volume + storage |
| `cluster-metadata-exporter` | sidecar (`cluster_metadata_exporter.py`) | Backs up FE metadata (`/opt/engine/fe/meta`) to blob on a cron. | engine FE shared volume + storage + audit_db |

In **local mode** the docker-compose stack only exercises `core-data-ingester`. The other modules require a queue and blob backend; they're not blocked from running locally if you wire your own emulators, but it's not the supported path.

---

## Repository layout

```
.
├── main.py                              # Entrypoint: dispatches by APPLICATION_NAME
├── entrypoint.sh                        # Docker entrypoint: picks main.py vs sidecar scripts
├── Dockerfile                           # python:3.11-slim-bookworm, non-root user (uid 1000)
├── config.ini                           # Section-based config; resolves ${ENV_VAR} substitutions
├── .env.example                         # Copy to .env and fill in
├── requirements.txt
├── pyfiles/
│   ├── hyperion_core/
│   │   ├── core_load_processor.py       # The pipeline. fhir_converter() + local_converter()
│   │   ├── normalizer.py                # FHIR JSON → tabular columns (the algorithm)
│   │   ├── transaction_manager.py       # Engine stream-load + 2PC transactions
│   │   ├── fhir_batch_processor.py      # Batch-load exporter (queue producer)
│   │   ├── fhir_batch_exporter.py       # Batch export helper
│   │   ├── fhir_event_processor.py      # Event-driven exporter (queue producer)
│   │   ├── fhir_event_exporter.py       # Event export helper
│   │   ├── fhir_scheduler.py            # Async scheduler / catch-up
│   │   ├── audit_lineage_manager.py     # Audit + lineage stream-load
│   │   ├── retry_manager.py             # 602/603 retry processor
│   │   ├── admin_grant_manager.py       # K8s sidecar: auto-grants on new DB creation
│   │   ├── root_password_manager.py     # K8s sidecar: rotates engine root pw
│   │   ├── cluster_metadata_exporter.py # K8s sidecar: backs up FE metadata
│   │   ├── cluster_metadata_restorer.py # Disaster recovery (manual run)
│   │   └── sidecar_init.py              # Shared sidecar base class
│   ├── adapters/
│   │   ├── interface.py                 # Abstract base classes for cloud adapters
│   │   ├── fhir_clients.py              # AzureFHIRClient + HapiFhirClient
│   │   ├── queue_clients.py             # AzureQueueClient (Service Bus)
│   │   └── storage_clients.py           # AzureStorageClient (Blob)
│   └── dependencies/
│       ├── prerequisites.py             # Startup validation + config parse
│       ├── handlers.py                  # Logging, signal handlers
│       ├── enum.py                      # ApplicationEnums, PipelineErrorCodes
│       ├── db_connection_pool.py        # Engine SQLAlchemy pool
│       ├── db_ops.py                    # Engine DML helpers
│       ├── df_ops.py                    # Shared-table flattening helpers (CC/Ref/Identifier)
│       ├── data_processing_error.py     # PipelineError + DataProcessingException
│       └── resource_manager.py          # Singleton for shutdown cleanup
├── schema/
│   ├── fhir.schema.json                 # Vendored FHIR R4 JSON Schema
│   └── deletion_attributes.json         # Bridge artifact: fields → common tables
└── tests/
    └── pytest/
        ├── unit/                        # Mock everything. 700+ tests.
        ├── integration/                 # Require Docker, engine, HAPI.
        ├── e2e/                         # Full pipeline end-to-end.
        └── mocks/                       # Shared fixtures and fakes.
```

The most interesting file for new contributors is **`pyfiles/hyperion_core/normalizer.py`**. To extend Hyperion to a new cloud provider (say, AWS), implement the three abstract base classes in `pyfiles/adapters/interface.py` (`FHIRServerClient`, `StorageClient`, `ServiceBusMessageQueueClient`) and wire them into the `main.py` dispatch block alongside the existing Azure clients.

---

## Configuration via `.env`

Hyperion Core reads its configuration from `config.ini`, which performs `${ENV_VAR}` substitution from the process environment. The canonical workflow is:

```bash
cp .env.example .env
# edit .env
docker run --env-file .env hyperion/core:local
```

`.env` is gitignored. Never commit secrets.

The three switches that matter most:

```ini
CLOUD_STORAGE=local    # or "azure"
SERVICEBUS=local       # or "azure"
FHIR_SERVICE=local     # or "azure"
```

Set all three to `local` for the HAPI demo, or all three to `azure` (and uncomment the Azure block at the bottom of `.env.example`) for an Azure/scaled deployment. The full env var list is in `.env.example`. It's grouped by section (engine, FHIR, pools, sidecars, Azure) with inline comments.

---

## Building and running with Docker

The image is `python:3.11-slim-bookworm`, runs as a non-root user (`hyperion`, uid 1000), and ships at roughly 230 MB. The same base image is used by `hyperion-util` so contributors don't context-switch between musl and glibc.

### Build

```bash
docker build -t hyperion/core:local .
```

### Run the default pipeline (core-data-ingester)

```bash
docker run --env-file .env hyperion/core:local
```

This is equivalent to setting `APPLICATION_NAME=core-data-ingester` in your `.env`.

### Run a different module

```bash
docker run --env-file .env -e APPLICATION_NAME=batch-load-exporter hyperion/core:local
```

Replace `batch-load-exporter` with any value from the [modules table](#modules--what-application_name-can-be). Command-line `-e` flags override values in `.env`, which is handy when you have one `.env` file and want to spin up several processors against the same backend.

### Run a sidecar

The three sidecars use the same image but a different entrypoint dispatch (see `entrypoint.sh:8-16`):

```bash
docker run --env-file .env -e APPLICATION_NAME=admin-grant-manager hyperion/core:local
docker run --env-file .env -e APPLICATION_NAME=root-password-manager hyperion/core:local
docker run --env-file .env -e APPLICATION_NAME=cluster-metadata-exporter hyperion/core:local
```

The sidecars require a shared volume mount to the engine FE log directory (`FE_LOG_FILE_PATH`, `FE_META_FOLDER_PATH`, `FE_PID_FILE` in `.env.example`). Standalone runs are only useful for development; in a Kubernetes deployment these are co-located with the engine FE pod.

### Override a single env var

```bash
docker run \
  --env-file .env \
  -e LOG_LEVEL=DEBUG \
  -e RESOURCE_TYPES=Patient,Observation \
  hyperion/core:local
```

### Logs

The container writes to stdout (captured by Docker / Kubernetes). Modules dispatched through `main.py` also write a rotating application log to `logs/<APPLICATION_NAME>.log` inside the container (10 MB × 10 backups). The sidecars (dispatched by `entrypoint.sh`) are stdout-only, and additionally tail and parse the FE log at `FE_LOG_FILE_PATH`.

---

## Running tests

Three tiers under `tests/pytest/`:

| Tier | Path | What it needs |
|---|---|---|
| Unit | `tests/pytest/unit/` | Nothing. Everything is mocked. |
| Integration | `tests/pytest/integration/` | Docker + the engine + HAPI (or matching emulators). |
| E2E | `tests/pytest/e2e/` | Full local docker-compose stack. |

```bash
# Unit (fast, runs in under a minute)
PYTHONPATH=. pytest tests/pytest/unit -q

# Integration (slow, boots Docker dependencies via fixtures)
PYTHONPATH=. pytest tests/pytest/integration -v

# End-to-end
PYTHONPATH=. pytest tests/pytest/e2e -v
```

**Convention worth flagging up front:** the unit tests import the modules under test **inside the test function bodies**, not at the top of the file. This is intentional. It keeps `tests/pytest/unit/` independent of import-time side effects (`load_dotenv()`, config parsing) so each test can patch env vars before the import resolves. If you see `from pyfiles... import X` inside a `def test_...():`, that's why; don't move it to module scope.

The unit tier ships with 700+ tests (743 at the v0.1.0 release). See [`tests/pytest/README.md`](tests/pytest/README.md) for the testing guide (fixture layout, mock strategy, what each tier is allowed to import).

---

## Production deployment notes

For a production deployment, run on Kubernetes against a managed Hyperion Engine (StarRocks) cluster.

- Each `APPLICATION_NAME` runs as its own Deployment / pod. `core-data-ingester` and the exporters scale horizontally; `batch-scheduler` is a singleton.
- The three sidecars (`admin-grant-manager`, `root-password-manager`, `cluster-metadata-exporter`) attach to the engine FE pod with a shared volume mounted at the FE log + metadata directories. They need filesystem access, not just network access.
- Secrets (FHIR client credentials, Service Bus connection strings, engine root password) are expected to come from a secret store: Azure Key Vault, or any secret store that injects env vars.
- Helm charts and Terraform are **not** part of this repository. Operators bring their own.

---

## Contributing

Contributions are welcome. A few things to know:

- **Where to engage.** The algorithm in `pyfiles/hyperion_core/normalizer.py` (plus the shared-table helpers in `pyfiles/dependencies/df_ops.py`) is the most interesting place to read and the most useful place to improve. If you want to add a new cloud adapter (AWS, GCP), the abstract base classes in `pyfiles/adapters/interface.py` are the seam.
- **Issues.** When filing a bug, please include: FHIR resource type, mode (`FHIR_SERVICE` / `CLOUD_STORAGE` / `SERVICEBUS` settings), engine version, and a minimal NDJSON sample if normalization is misbehaving. Performance issues should include resource count + timing.
- **Tests.** New code lands with unit tests. The "imports inside test functions" convention is real. Please follow it.
- **CONTRIBUTING.md**: a longer guide is forthcoming.

---

## License

Apache 2.0. See [LICENSE](../LICENSE).
