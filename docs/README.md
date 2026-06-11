# Hyperion documentation

Reference docs that sit behind the [project README](../README.md).

| Doc | What's in it |
|---|---|
| [architecture.md](architecture.md) | Data flow diagram, key design properties, the two operating modes, repository layout |
| [configuration.md](configuration.md) | Complete environment-variable reference |
| [development.md](development.md) | Dev workflow, common operations, tests, advanced compose operations |
| [queries.md](queries.md) | Example SQL against the FHIR-shaped tables and shared tables |
| [deployment-azure.md](deployment-azure.md) | Full Azure deployment walkthrough: prerequisites, scaling up, sidecars |
| [troubleshooting.md](troubleshooting.md) | Symptoms and fixes |

Service internals live in the child READMEs: [`core/`](../core/README.md) (the pipeline) and [`util/`](../util/README.md) (the bootstrap).
