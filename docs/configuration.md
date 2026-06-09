# Configuration reference

All configuration is via environment variables. The parent compose reads from `.env` (which is gitignored). Below is the canonical list — copy `.env.example` to `.env` and edit from there.

---

## Mode switches

| Variable | Default | What it controls |
|---|---|---|
| `FHIR_SERVICE` | `local` | Where FHIR data comes from. `local` = HAPI, `azure` = Azure Health Data Services. |
| `CLOUD_STORAGE` | `local` | Where staged NDJSON lives in Azure mode (Azure Blob). In `local`, nothing is staged. |
| `SERVICEBUS` | `local` | Whether to use Azure Service Bus queues. In `local`, the pipeline pulls directly from FHIR. |
| `DEPLOYMENT_TYPE` | `local` | Coarse switch for util's pre-flight checks. |
| `LOG_LEVEL` | `INFO` | `INFO` / `DEBUG` / `ERROR`. |

---

## Hyperion Engine

| Variable | Default | Notes |
|---|---|---|
| `SILVER_LAYER_QUERY_SERVER` | `starrocks-fe:9030` | FE MySQL endpoint. Change to your cluster in Azure. |
| `SILVER_LAYER_HTTP_SERVER` | `starrocks-fe:8030` | FE HTTP endpoint (stream-load). |
| `SILVER_LAYER_CATALOG` | `default_catalog` | Engine catalog name. |
| `SILVER_LAYER_CORE_DATABASE` | `_hyperion_core_` | Where FHIR-shaped tables live. |
| `SILVER_LAYER_AUDIT_DATABASE` | `_hyperion_audit_` | Pipeline audit/lineage tables. |
| `SILVER_LAYER_ROOT_USERNAME` | `root` | Engine root (used by util for bootstrap only). |
| `SILVER_LAYER_ROOT_PASSWORD` | (empty) | Fresh engine has no root password. |
| `SILVER_LAYER_STORAGE_VOLUME` | `hyperion_storage_volume` | Name of the storage volume util creates. |
| `SILVER_LAYER_REPLICA` | `1` | Tablet replication. `1` for single-node demo; production uses `3`. |
| `SILVER_LAYER_TRANSACTION` | `false` | Use 2-phase-commit when stream-loading. `true` for Azure (atomic across queue+blob); `false` for local. |
| `SERVICE_ACCOUNT_USERNAME` | `hyperion_service` | Engine user util creates; core uses this at runtime. |
| `SERVICE_ACCOUNT_PASSWORD` | (empty) | Set a real password for any non-local deployment. |
| `ADMIN_ROLE` | `admin` | Role created by util for admin operations. |

---

## FHIR server

| Variable | Default | Notes |
|---|---|---|
| `FHIR_SERVER_URL` | `http://hapi-fhir:8080/fhir` | Local (HAPI) only. Azure mode uses `AZURE_FHIR_SERVER_BASEURL` (see the Azure block). |
| `FHIR_SERVER_TIMEOUT_SECONDS` | `60` | Core's HTTP timeout per request. |
| `LOCAL_FHIR_SERVER_TIMEOUT_SECONDS` | `30` | Util's HTTP timeout per request. |
| `RESOURCE_TYPES` | `Patient,Observation,Condition,Encounter` | Which resource types core pulls. Add more from the [Synthea generator output](#synthea-data-generator-parent-compose-only) section. |
| `LOOKBACK_DAYS` | `365` | Time window for local-mode FHIR pulls (Synthea generates data across patients' full lifespans, so this matters). |

---

## Storage (Azure or MinIO)

| Variable | Default | Notes |
|---|---|---|
| `LOCAL_STORAGE_ENDPOINT` | `http://minio:9000` | MinIO endpoint. |
| `LOCAL_STORAGE_LOCATIONS` | `s3://hyperion/` | Bucket URI util uses when creating the storage volume. |
| `LOCAL_STORAGE_ACCESS_KEY_ID` | `minioadmin` | MinIO root user. |
| `LOCAL_STORAGE_ACCESS_KEY_SECRET` | `minioadmin123` | MinIO root password. |
| `LOCAL_STORAGE_REGION` | `us-east-1` | MinIO doesn't care, but the engine's S3 client demands a value. |
| `AZURE_BLOB_STORAGE_*` | (commented out) | Container, endpoint, version — see the Azure block in `.env.example`. |

---

## Synthea data generator (parent compose only)

| Variable | Default | Notes |
|---|---|---|
| `SYNTHEA_PATIENT_COUNT` | `10` | How many synthetic patients to generate. Each ≈ 50–200 FHIR resources. 10 patients ≈ 60–90s; 100 patients ≈ 5–8 min. |
| `SYNTHEA_SEED` | `12345` | Deterministic seed — same seed produces identical data. |
| `SYNTHEA_VERSION` | `3.3.0` | Synthea release tag; jar is downloaded once and cached. |
| `SYNTHEA_INCLUDE_HOSPITAL` | `true` | Exports `hospitalInformation*.json` (Organization + Location bundles). **Required** because patient bundles reference these via NPI match URLs — disabling will cause HAPI to reject patient bundles. The loader stages loads to handle this dependency. |
| `SYNTHEA_INCLUDE_PRACTITIONER` | `true` | Exports `practitionerInformation*.json` (Practitioner + PractitionerRole bundles). Same dependency story as hospital — patient bundles reference practitioners by NPI, so this must be on. |
| `SYNTHEA_ONLY_ALIVE` | `true` | Set `false` to include deceased patients (Synthea models full lifespans). |

### Ingesting more resource types

Synthea generates ~15–20 FHIR R4 resource types per patient (Patient, Encounter, Condition, Observation, Procedure, MedicationRequest, Immunization, DiagnosticReport, Claim, ExplanationOfBenefit, and more). Every FHIR R4 type already has a flattened table in `_hyperion_core_` (util creates one per type at bootstrap), so to ingest beyond the default four just expand `RESOURCE_TYPES`. Suggested presets:

- **Clinical:** `Patient,Observation,Condition,Encounter,Procedure,MedicationRequest,Immunization,DiagnosticReport,AllergyIntolerance,CarePlan`
- **Clinical + Claims:** add `Claim,ExplanationOfBenefit,Coverage`

---

## Pipeline tuning (core)

| Variable | Default | Notes |
|---|---|---|
| `NDJSON_FILE_SIZE` | `1000` | Records per NDJSON file when Azure mode stages to blob. |
| `FHIR_PULL_MAX_RETRY_COUNT` | `3` | Retries per FHIR HTTP request. |
| `DB_POOL_SIZE` | `5` | SQLAlchemy pool size for engine connections. |
| `PROCESSING_THREADS` | `4` | Worker threads for normalization. |
| `MESSAGE_BATCH_SIZE` | `10` | Service Bus messages per receive (Azure mode). |
| `CORES_CONVERTER` / `CORES_EXPORTER` | `2` | Concurrent processors. |
| `AUDIT_BATCH_SIZE` | `100` | Audit rows per stream-load. |
| `AUDIT_FLUSH_INTERVAL` | `30` | Seconds between audit flushes. |
| `IS_AUDIT` / `IS_LINEAGE` | `false` | Whether to write audit / lineage rows. Enable for compliance traceability. |
| `RETRY_MESSAGE_DELAY_TIME` | `60` | Seconds to wait before retrying a failed message (Azure mode). |
| `DEFAULT_META_SOURCE` | `hyperion-local` | String stored in `meta_source` column of every ingested row. |

---

## Schema generation (util)

| Variable | Default | Notes |
|---|---|---|
| `SCHEMA_OVERWRITE_FLAG` | `true` | Regenerate `silver_layer_all.sql` from the FHIR schema on each bootstrap. |
| `DATABASE_INITIALIZATION_FLAG` | `true` | Execute the generated DDL against the engine. |
