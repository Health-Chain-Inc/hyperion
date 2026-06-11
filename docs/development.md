# Development workflow

Working on `core/` or `util/` code, or building integrations against the OSS pipeline.

---

## Editing code

Both `core/` and `util/` are normal Git checkouts. Edit code in place, then rebuild and restart the affected service:

```bash
docker compose up -d --build hyperion-util   # rebuild util image and re-run bootstrap
docker compose up -d --build hyperion-core   # rebuild core and re-run pipeline
```

---

## Common operations

### Change the number of synthetic patients

```bash
# In .env:
SYNTHEA_PATIENT_COUNT=50

# Then trigger re-generation (drops the synthea-output volume so it regenerates):
docker compose down -v
docker compose up
```

### Ingest more FHIR resource types

```bash
# In .env:
RESOURCE_TYPES=Patient,Observation,Condition,Encounter,Procedure,MedicationRequest,Immunization

# Restart core; util already created tables for every FHIR R4 type so no rebootstrap needed:
docker compose up -d --force-recreate hyperion-core
```

### Reset everything (local)

```bash
docker compose down -v
```

Drops named volumes (`minio_data`, `synthea-output`) so the next `up` regenerates from scratch.

For switching to or tearing down the Azure stack, see [`deployment-azure.md`](deployment-azure.md).

---

## Running tests

Unit tests run in seconds with no Docker; integration and e2e tests need the compose stack. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and [`../core/tests/pytest/README.md`](../core/tests/pytest/README.md) for the exact commands and test layout.

---

## Tighter local dev loop

Instead of `docker compose up --build` on every code change, run core directly from the Python checkout:

```bash
cd core
pip install -r requirements.txt
cp ../.env .env                              # share the parent compose's env
# Override hostnames to localhost-exposed ports:
echo "SILVER_LAYER_QUERY_SERVER=localhost:9030" >> .env
echo "SILVER_LAYER_HTTP_SERVER=localhost:8030" >> .env
echo "FHIR_SERVER_URL=http://localhost:8080/fhir" >> .env

PYTHONPATH=. python main.py
```

This skips the Docker rebuild cycle: edit a `.py`, re-run, repeat.

---

## Performance notes: speeding up the local loop

The first `docker compose up` takes ~15 min, dominated by HAPI FHIR's Spring Boot cold start (5-10 min). Subsequent runs after `docker compose down` (without `-v`) take ~12 min because HAPI's database, Synthea bundles, and MinIO data are all persisted to named volumes; the compose skips the Synthea regeneration and the 3-stage bundle load entirely.

Phase times after the first run:

| Phase | First run | After `down` (no `-v`) | Why |
|---|---|---|---|
| MinIO + FE/CN cold start | 3-4 min | 3-4 min | Same |
| HAPI cold start | 5-10 min | 5-10 min | Spring Boot warm-up doesn't get cheaper from volume reuse |
| Synthea generate | 1-2 min | < 1 sec | Skipped: bundles already in `synthea-output` volume |
| Synthea load (3-stage POST) | 1-2 min | < 1 sec | Skipped: `synthea-loader` queries HAPI's Patient count and exits 0 if > 0 |
| Util bootstrap (149 DDLs: 146 resource + 3 common tables) | 2-3 min | 2-3 min | FE metadata is not currently persisted across `down` (see below) |
| Core pipeline | 4-5 min | 4-5 min | Re-pulls from HAPI; core's `updated_date` dedup logic catches no-ops |

To force a full reset (regenerate Synthea, re-bootstrap engine, reload everything): `docker compose down -v`.

### Future optimization: engine FE metadata persistence

A further ~4 min could be cut from subsequent runs by also persisting the engine's FE metadata directory (`/opt/starrocks/fe/meta`) to a named volume. Util's `IF NOT EXISTS` DDL would then no-op in ~30 sec instead of taking 2-3 min, and core's dedup logic would catch all resources as duplicates and exit in ~30 sec instead of running a full pull.

This is intentionally **not** implemented today because:

- The FE meta directory is sensitive to FE process lifecycle (FE writes to it continuously; an unclean shutdown can leave it in a state that requires `--reset_fe` on next boot).
- Reproducibility for contributors is higher priority than 4 min of speedup; a clean re-bootstrap is the safer default for a demo repo.

If you want to try it locally:

```yaml
starrocks-fe:
  volumes:
    - fe-meta:/opt/starrocks/fe/meta

volumes:
  fe-meta:
```

Test by running through `down` + `up` cycles and confirming util's bootstrap completes idempotently each time.

## Advanced compose operations

### Run only specific services

```bash
docker compose up minio starrocks-fe starrocks-cn hapi-fhir
# Use case: bring up infra, then run core/util manually for tighter dev loop.
```

### Reset just the engine state but keep the Synthea jar cached

```bash
docker compose down
docker volume rm hyperion-open-source_minio_data
```

The next `up` re-bootstraps the engine but skips Synthea's ~30 MB JAR download.

### Force a rebuild of one service

```bash
docker compose up -d --force-recreate --build hyperion-core
```

Useful when you've edited core/ code and only want the pipeline restarted without touching the engine, HAPI, or util.

---

## Going deeper

| You want to… | Read this |
|---|---|
| Understand the pipeline algorithm (normalizer, shared tables, FHIR JSON Schema → DDL) | [`../core/README.md`](../core/README.md) |
| Run `core` alone against your own engine + FHIR | [`../core/README.md`](../core/README.md): *Option B* |
| Modify the schema (which FHIR resources, which columns) | [`../util/README.md`](../util/README.md) + `util/schema/fhir.schema.json` |
| Run `util` alone to bootstrap an engine you manage | [`../util/README.md`](../util/README.md) |
| Add a new cloud provider adapter | [`../core/pyfiles/adapters/interface.py`](../core/pyfiles/adapters/interface.py) implements three abstract base classes (FHIR / Storage / Queue). Add your adapter, wire it into `core/main.py`. |
| Understand the testing layout and conventions | [`../core/tests/pytest/README.md`](../core/tests/pytest/README.md) |
