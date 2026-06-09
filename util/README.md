# hyperion-util

One-shot bootstrap utility for the **Hyperion** FHIR → SQL pipeline.

Hyperion transforms HL7 FHIR R4 healthcare data into a flat, relational SQL structure. `hyperion-util` prepares the SQL engine before the pipeline starts: it creates the storage volume, the core and audit databases, the service-account role, and one table per FHIR resource type derived directly from the FHIR schema.

This image is designed to be run **once** against a fresh engine, then exit. Re-running is safe (operations are guarded by `IF NOT EXISTS` checks).

---

## Table of contents

- [What this utility does](#what-this-utility-does)
- [Pre-requisites](#pre-requisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Running standalone](#running-standalone)
- [Running with hyperion-core](#running-with-hyperion-core)

---

## What this utility does

1. **Initialize storage volume** — creates a StarRocks storage volume backed by Azure ADLS / ADLS Gen2 (production) or MinIO over the S3 API (local demo).
2. **Initialize core database** — creates the `_hyperion_core_` database.
3. **Initialize audit database** — creates the `_hyperion_audit_` database for pipeline lineage and audit tables.
4. **Create FHIR resource tables** — reads `schema/fhir.schema.json` and emits one flattened table per FHIR R4 resource type in the core database.
5. **Create service-account user** — provisions the engine user that `hyperion-core` uses at runtime.

The utility exits after step 5. There is no long-running process.

---

## Pre-requisites

The bootstrap needs **both** the engine and a FHIR server reachable. The util queries the FHIR server's `/metadata` endpoint to discover which resource types the server supports — that list drives which tables get created.

1. **Hyperion engine** (StarRocks 3.4+):
   - MySQL-protocol port (default `9030`)
   - HTTP stream-load port (default `8030`)
   - Root credentials (used only during bootstrap)

2. **FHIR R4 server**:
   - HAPI FHIR for local development (the bundled compose runs one)
   - Azure Health Data Services FHIR for production
   - Must expose a healthy `/metadata` endpoint *before* util runs

For local development a one-command stack is provided in [`docker-compose.local-minio.yml`](docker-compose.local-minio.yml) — it brings up the infrastructure util needs:

1. **MinIO** — S3-compatible storage backing the engine's shared-data volume.
2. **Hyperion engine** (StarRocks shared-data mode) pointed at MinIO.
3. **HAPI FHIR** — empty FHIR R4 server (util reads `/metadata` only — no data needed for the bootstrap).
4. **hyperion-util** — one-shot. Runs `python main.py bootstrap` against the engine — storage volume, core / audit databases, FHIR resource tables, service account.

This stack validates that **util** works end-to-end. It does not seed HAPI with FHIR data — that's the parent mono-repo's `docker-compose.yml` responsibility, which orchestrates the full demo (util + Synthea data generation + HAPI loading + `hyperion-core` pipeline). When running the parent compose, util's role is unchanged: one-shot bootstrap, exits 0, gets out of the way.

---

## Quick start

### Option A — Local demo (MinIO + engine + HAPI FHIR + util, one command)

```bash
git clone https://github.com/Health-Chain-Inc/hyperion.git
cd hyperion/util
cp .env.example .env
docker compose -f docker-compose.local-minio.yml up --build
```

This single command brings up MinIO, the engine, HAPI FHIR, then runs `hyperion-util` once (it exits 0 when the bootstrap is done) — the long-running services keep going. Inspect with `docker compose -f docker-compose.local-minio.yml ps`.

After this finishes, the engine has `_hyperion_core_`, `_hyperion_audit_`, all FHIR tables, and the service-account user. `hyperion-core` (the pipeline) can be pointed at the same engine to load data.

> Re-running is largely safe — the storage volume, resource tables, and service account are all existence-guarded. The two `CREATE DATABASE` statements are not yet guarded, so a re-run against an already-bootstrapped engine logs a benign "database already exists" error for those steps.

### Option B — Build and run against your own engine

```bash
git clone https://github.com/Health-Chain-Inc/hyperion.git
cd hyperion/util
cp .env.example .env             # edit to point at your engine + FHIR server
docker build -t hyperion/util:local .
docker run --rm --env-file .env hyperion/util:local
```

---

## Configuration

All configuration is via environment variables — `config.ini` reads from `${VAR}` placeholders and `.env.example` documents every variable.

> **Sharing `.env` with `hyperion-core`:** the same `.env` file works for both `util/` and `core/`. Util reads bootstrap-only vars (root credentials, schema flags) and core reads runtime-only vars (queue / Service Bus / Blob Storage), and both share the engine + FHIR connection vars. Keep one `.env` at the repo root (the parent compose uses it), or copy it into each directory for standalone runs.

Highlights:

| Var | Purpose |
|---|---|
| `DEPLOYMENT_TYPE` | `local` or `azure` |
| `FHIR_SERVICE` | `azure` (Azure Health Data Services) — set `DEPLOYMENT_TYPE=local` for HAPI FHIR / local mode |
| `CLOUD_STORAGE` | `local` (MinIO over S3 API) or `azure` (ADLS / ADLS Gen2) |
| `SILVER_LAYER_QUERY_SERVER` | engine MySQL endpoint, e.g. `host:9030` |
| `SILVER_LAYER_ROOT_USERNAME` / `SILVER_LAYER_ROOT_PASSWORD` | engine root credentials (only used during bootstrap) |
| `SERVICE_ACCOUNT_USERNAME` / `SERVICE_ACCOUNT_PASSWORD` | service-account user that `hyperion-core` will use at runtime (created by util during bootstrap) |
| `LOCAL_STORAGE_*` | MinIO endpoint, bucket, and keys (when `CLOUD_STORAGE=local`) |
| `AZURE_BLOB_STORAGE_*` | ADLS container, endpoint, version (when `CLOUD_STORAGE=azure`) |

See `.env.example` for the full list.

---

## Running standalone

You don't need `hyperion-core` to use this utility — it's useful on its own when you want a FHIR-shaped relational schema on top of the Hyperion engine and intend to populate it via your own ETL.

```bash
docker run --rm --env-file .env hyperion/util:local
```

(Build the image first with `docker build -t hyperion/util:local .` — same tag as Option B.)

The container runs `python main.py`, exits with `0` on success, and writes logs to stdout.

---

## Running with hyperion-core

When you also want the pipeline (HAPI / Azure FHIR → engine), `hyperion-util` must run **once before** `hyperion-core` starts ingesting. The expected orchestration is:

```
engine (StarRocks)
   └── MinIO   (local mode only)
        └── hyperion-util         (runs once, creates schema, exits 0)
              └── hyperion-core   (long-running pipeline)
```

In Docker Compose, that's expressed with `depends_on: { condition: service_completed_successfully }` on `hyperion-util`. The parent mono-repo's `docker-compose.yml` wires this end-to-end.

---

## Development

```bash
pip install -r requirements.txt
pytest                                  # run the unit-test suite
```

Tests live under `tests/`. Generated artifacts:

- `schema/silver_layer_all.sql` — the DDL the utility executes against the engine (regenerated from `fhir.schema.json` on each run).
