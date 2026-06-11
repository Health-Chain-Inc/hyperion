# Troubleshooting

Symptoms encountered during local or Azure deployment, and how to fix them.

| Symptom | Likely cause | Fix |
|---|---|---|
| `hyperion-util-bootstrap` exits 0 but engine has no tables | A downstream step swallowed an exception. Re-check util's logs in full. | `docker compose logs hyperion-util-bootstrap` and look for an earlier ERROR before the "Bootstrap complete" line. |
| `hyperion-core-pipeline` crashes with `'dict' object has no attribute 'lower'` | Your `.env` is missing a required variable (configparser inserted `None`, configparser rejects it). | Compare your `.env` against `.env.example`; ensure all referenced vars are set. |
| `Stream load failed ... no valid Basic authorization` | Custom client used `allow_redirects=True` and lost auth across the FE→CN port hop. Shouldn't happen with the shipped code. | If you've modified `_stream_load_local` / `TransactionManager.transaction`, reapply the manual-redirect-with-auth-replay pattern. |
| HAPI FHIR stays "unhealthy" for 10+ minutes | HAPI's image is distroless. Docker's HEALTHCHECK can't probe it. The `hapi-wait` sidecar does this from outside. | Wait for `hapi-wait` to print "HAPI FHIR is ready". 5-10 min cold start on Windows. |
| `BE registered as 127.0.0.1` (legacy `starrocks/allin1-ubuntu` setup) | The single-container allin1 image hardcodes `priority_networks=127.0.0.1`. | This compose uses the split FE + CN topology with `--host_type FQDN`. If you're seeing this, you're running the wrong compose file. |
| `LF will be replaced by CRLF` warnings on Windows | Git's autocrlf converting line endings. | Repo ships `.gitattributes` locking `*.sh` to LF. Harmless warning, leave it. |
| `entrypoint.sh: no such file or directory` inside container | CRLF in entrypoint.sh sneaks past `.gitattributes` (rare). | Run `sed -i 's/\r$//' core/entrypoint.sh` then rebuild. |
| Container builds work but compose fails with `network is still in use` | An older container is orphaned from a previous topology. | `docker compose down --remove-orphans -v` then `up`. |
| `docker compose up` hangs on "Building hyperion-util" / "hyperion-core" | First-time Python + apt + pip install. | Wait: typically 60-120s on a warm cache, longer cold. |
| Azure: no rows in `fhir_audit` after 10 minutes | Service Bus queue is empty (nothing to ingest), or the FHIR service principal lacks read scope. | Check the Service Bus `event` queue for messages; check the Azure FHIR audit log for 401/403 from your service principal. |
| Azure: util-bootstrap fails with `Storage volume creation failed` | `AZURE_BLOB_STORAGE_VERSION` mismatch between fe.conf and the storage-volume TYPE util generates. | Both must agree: `1` for AZBLOB, `2` for ADLS2. Re-check `.env`, `docker compose down -v`, then `up`. |

## Power BI / ODBC: "Test connection" succeeds but queries fail

The MySQL ODBC driver defaults to **server-side prepared statements**, which the engine does not fully support, so the ODBC administrator's "Test" button (a bare connect) passes, but Power BI's first real query (issued via `SQLPrepare`) fails.

**Fix:** in your DSN's advanced/details options enable *"Prepare statements on the client"* (`NO_SSPS=1`).

Recommended DSN settings (64-bit MySQL ODBC Unicode driver):

| Setting | Value |
|---|---|
| `SERVER` / `PORT` | your engine host / `9030` |
| `DATABASE` | `_hyperion_core_` |
| User | set it in the DSN's User field (avoids Power BI's empty-password dialog quirk) |
| `NO_SSPS` | `1` |
| `SSLMODE` | `DISABLED` for the local demo (plaintext) |

Alternatively, use Power BI's **MySQL database** connector (Connector/NET) instead of ODBC. It needs no DSN.
