# Architecture

How the pieces fit together: the pipeline, the engine, object storage, and the one-shot bootstrap.

## Data flow

```
                  ┌──────────────────────────────────────────┐
                  │     FHIR R4 Server                       │
                  │     • HAPI FHIR  (local demo)            │
                  │     • Azure Health Data Services FHIR   │
                  │       (Azure mode)                       │
                  └─────────────┬────────────────────────────┘
                                │ REST API (search + pagination)
                                │ or Service-Bus queue (Azure mode)
                                ▼
                  ┌─────────────────────────────────────────┐
                  │   hyperion-core   (./core/)             │
                  │                                         │
                  │   adapters/fhir_clients.py              │
                  │           │                             │
                  │           ▼                             │
                  │   hyperion_core/normalizer.py           │
                  │           │  FHIR JSON Schema →         │
                  │           │  flat columns + shared      │
                  │           │  tables (CodeableConcept,   │
                  │           │  Reference, Identifier)     │
                  │           ▼                             │
                  │   hyperion_core/transaction_manager.py  │
                  └─────────────┬───────────────────────────┘
                                │ HTTP stream-load (JSON)
                                ▼
                  ┌──────────────────────────────────────────┐
                  │  Hyperion Engine, StarRocks 3.4          │
                  │  shared-data mode                        │
                  │   ┌─ FE  Frontend (metadata, SQL planning)│
                  │   │  └─ MySQL :9030, HTTP :8030          │
                  │   └─ CN  Compute Node (stateless compute)│
                  │      └─ HTTP :8040                       │
                  └─────────────┬────────────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────────────────────┐
                  │  Object storage (S3-compatible)          │
                  │  • MinIO         (local demo)            │
                  │  • Azure Blob /  (Azure mode)            │
                  │    ADLS Gen2                             │
                  │  (compressed columnar files,             │
                  │   single source of truth)                │
                  └──────────────────────────────────────────┘

                Bootstrap (one-shot, runs before core):
                  ┌─────────────────────────────────────────┐
                  │   hyperion-util   (./util/)             │
                  │   • Creates storage volume              │
                  │   • Creates _hyperion_core_,            │
                  │     _hyperion_audit_ databases          │
                  │   • Generates one table per FHIR R4     │
                  │     resource type from the JSON schema  │
                  │   • Creates service-account engine user │
                  └─────────────────────────────────────────┘
```

## Key design properties

**Schema is derived, not authored.** Util discovers the resource types from the source FHIR server's `/metadata` CapabilityStatement and emits one table per type, with each table's columns flattened from `schema/fhir.schema.json`. Against the bundled HAPI server (which advertises the full set of FHIR R4 resource types), that's every type, not a hand-picked subset. When the FHIR spec adds a resource or evolves an existing one, the schema regenerates from the updated schema file with no code changes. Existing data stays compatible.

**Batch and event load processing.** The pipeline supports two ingestion modes that share one normalization path: **batch load** for scheduled time-window pulls (catch-up, historical backfill, periodic refresh) and **event load** for change-driven real-time ingestion (Azure mode only, driven by Service Bus queues; local mode supports batch load only). Same tables, same audit lineage, regardless of how the data arrived.

**Compute is decoupled from storage.** The Hyperion Engine runs in **shared-data** mode. Compute and storage are fully separated: table data lives as the engine's native columnar files (LZ4-compressed) in object storage (Azure Blob / ADLS Gen2 / S3 / MinIO), with the engine managing file layout, partitioning, and metadata. Compute nodes are stateless and read directly from object storage. Scale compute up during heavy analytics windows and shrink it when idle, with no rebalancing and no rebuild. Storage cost grows with data; compute cost grows with workload, and the two move independently.

**No bronze/silver/gold triplication.** FHIR-shaped silver tables are the only stored representation: no separate bronze (raw FHIR JSON files) or gold (curated marts) physical copies. Classic lakehouse pipelines store the same data three times across staging layers; Hyperion stores it once.

**Standard SQL clients connect natively.** Power BI, Tableau, dbt, DBeaver, Metabase, and every popular BI tool connect over the MySQL wire protocol on port 9030; any MySQL JDBC / ODBC client works without a translation gateway. There's no proprietary client library and no protocol bridge.

## Two operating modes

Each subsystem (FHIR server, storage, queue) has its own mode switch. You can mix and match.

| Env var | `local` value | `azure` value |
|---|---|---|
| `FHIR_SERVICE` | HAPI FHIR (in compose) | Azure Health Data Services FHIR |
| `CLOUD_STORAGE` | No blob staging; in-memory normalize → stream-load | Azure Blob Storage / ADLS Gen2 |
| `SERVICEBUS` | No queue; direct pull from FHIR | Azure Service Bus (event / batch / retry / audit) |

**Common combinations:**

| `FHIR_SERVICE` | `CLOUD_STORAGE` | `SERVICEBUS` | What this is |
|---|---|---|---|
| `local` | `local` | `local` | Full local demo. `docker-compose.yml`. |
| `azure` | `azure` | `azure` | Full Azure mode. `docker-compose.azure.yml`. |
| `azure` | `local` | `local` | Smoke test against a real Azure FHIR with no queue/blob. |

## Repository layout

```
hyperion-open-source/
├── core/                       # hyperion-core: the pipeline (FHIR → engine)
├── util/                       # hyperion-util: one-shot engine bootstrap
├── docs/                       # deployment, configuration, development, troubleshooting
├── docker-compose.yml          # parent compose: full local demo
├── docker-compose.azure.yml    # parent compose: hybrid Azure deployment
├── .env.example                # shared env template; copy to .env
└── README.md                   # project overview
```

**`core/` and `util/`** are the two services that make up Hyperion. Each ships its own `Dockerfile` and its own README; see the [Going deeper](../README.md#going-deeper) table for when to read which.

**The two compose files** at the repository root orchestrate the local demo (`docker-compose.yml`) and the hybrid Azure deployment (`docker-compose.azure.yml`).
