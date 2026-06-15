# Hyperion

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Query FHIR with plain SQL.**

Hyperion points at a FHIR R4 API and pulls FHIR R4 resources into a columnar database that speaks the MySQL wire protocol. One table per resource type, columns that mirror FHIR R4. Connect any SQL client and start querying.

No FHIRPath. No unnesting JSON. No driver to install. Power BI, Tableau, dbt, DBeaver, Metabase, or your psql-but-for-mysql of choice: if your tool talks to MySQL, it talks to Hyperion.

## Why you'd want this

FHIR is built for exchange: deeply nested JSON, designed to move one patient between systems. The second you want a population answer, you're either writing FHIRPath, hand-rolling a flattening pipeline into a warehouse, or authoring SQL-on-FHIR ViewDefinitions one by one. Then you maintain that forever as the spec moves and profiles change.

Hyperion skips all of it:

- **It's just SQL.** Tables and columns map to FHIR R4 directly, so `JOIN`, `GROUP BY`, and your existing dbt models work unchanged. Nothing new to learn.
- **It's just MySQL on the wire.** Power BI, Tableau, dbt, DBeaver, Metabase, JDBC/ODBC clients, BI tools, ORMs, and migration runners all connect over the MySQL wire protocol with zero special handling. No proprietary client.
- **The schema generates itself.** Every table is derived mechanically from the FHIR R4 (4.0.1) JSON Schema. New resource or new element? Re-bootstrap, not a code change. You never hand-write or hand-maintain DDL. As the spec evolves, the schema evolves with it.
- **Profiled data lands in the same tables.** US Core and other profiles constrain the same base R4 resources Hyperion already models, so profiled data lands straight into the existing columns. Hyperion stores the base resource as-is; it does not validate or enforce profiles.
- **Compute and storage scale separately.** Built on shared-data [StarRocks 3.4](https://github.com/StarRocks/starrocks). Burst compute for a heavy query window, shrink it when idle; data lives in Azure Blob, ADLS Gen2, S3, or MinIO.
- **Live or batch.** In Azure mode it stream-loads every change in real time via Service Bus. The local demo is a single batch pass: clone, point it at a FHIR endpoint, start querying in minutes.
- **ML-ready.** Connect Databricks (or any MySQL-compatible feature/ML pipeline) to the engine for downstream ML workloads.

## What Hyperion is not

- **Not a FHIR server.** It consumes a FHIR API (HAPI, Azure Health Data Services); it does not serve one.
- **Not an EHR or a replacement for one.** It's an analytics layer downstream of your clinical systems.
- **Not a validator or terminology service.** Resources are ingested as-is; validation happens upstream.
- **Not a transactional store.** The engine is columnar, built for analytical queries, not record-by-record CRUD.
- **Not an HL7 SQL-on-FHIR (v2) ViewDefinition implementation.** Same problem, solved with materialized tables instead of views, so there's nothing to author.

## Up and running

**Requires:** Docker Desktop (Mac/Windows) or Docker Engine 24+ (Linux); ~10 GB free disk; ~8 GB free RAM.

```bash
git clone https://github.com/Health-Chain-Inc/hyperion.git
cd hyperion
cp .env.example .env
docker compose up --build
```

### Check it's live

Confirm the engine is in shared-data mode and the compute node registered:

```sql
ADMIN SHOW FRONTEND CONFIG LIKE 'run_mode';
-- expect: run_mode = shared_data

SHOW STORAGE VOLUMES;
-- expect: hyperion_storage_volume

SHOW COMPUTE NODES\G
-- expect: Alive: true
```

Run these from any MySQL client against `localhost:9030`, or through the container:

```bash
docker exec -it hyperion-starrocks-fe \
  mysql -h 127.0.0.1 -P 9030 -u root \
  -e "ADMIN SHOW FRONTEND CONFIG LIKE 'run_mode';"
```

Example queries against the FHIR-shaped tables → [`docs/queries.md`](docs/queries.md).

## Going deeper

| You want to… | Read this |
|---|---|
| How the pieces fit together: diagram, key design, operating modes, repo layout | [`docs/architecture.md`](docs/architecture.md) |
| Example SQL against the FHIR-shaped + shared tables | [`docs/queries.md`](docs/queries.md) |
| Complete environment-variable reference | [`docs/configuration.md`](docs/configuration.md) |
| Dev workflow, common operations, tests, advanced compose | [`docs/development.md`](docs/development.md) |
| Full Azure deployment walkthrough (prereqs, scaling up, sidecars) | [`docs/deployment-azure.md`](docs/deployment-azure.md) |
| Symptoms and fixes | [`docs/troubleshooting.md`](docs/troubleshooting.md) |
| Pipeline internals (normalizer, shared tables, FHIR JSON Schema → DDL) | [`core/README.md`](core/README.md) |
| Modify the schema (which FHIR resources, which columns) | [`util/README.md`](util/README.md) + `util/schema/fhir.schema.json` |

All docs are indexed in [`docs/`](docs/README.md).

## Intended use

Hyperion is data-engineering infrastructure for analytics. It is not a medical device, is not validated or intended for clinical decision-making or patient care, and deploying it does not by itself satisfy HIPAA, SOC 2, or any other regulatory obligation; those remain the responsibility of the deploying organization.

## Community and contributing

- **Questions / bugs**: open a [GitHub issue](../../issues).
- **Contributing**: see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, conventions, and the PR process.
- **Security issues**: please report privately via [SECURITY.md](SECURITY.md), not a public issue.
- **Code of conduct**: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) (Contributor Covenant).

## License

Apache 2.0. See [LICENSE](LICENSE).
