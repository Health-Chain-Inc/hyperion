# Contributing to Hyperion

Thank you for your interest in contributing. Hyperion is a FHIR R4 → SQL ingestion pipeline built on StarRocks. The most interesting places to contribute are the normalization algorithm (`core/pyfiles/hyperion_core/normalizer.py`) and the cloud adapter layer (`core/pyfiles/adapters/`).

---

## Getting started

### Prerequisites

- Docker Desktop (Mac/Windows) or Docker Engine 24+ (Linux)
- Python 3.11+
- ~10 GB free disk, ~8 GB free RAM (for the full local stack)

### Local dev setup

```bash
git clone https://github.com/Health-Chain-Inc/hyperion.git
cd hyperion
cp .env.example .env
docker compose up           # full local demo: HAPI + MinIO + StarRocks + pipeline
```

See [`docs/development.md`](docs/development.md) for tighter dev-loop options (running core directly from Python without a Docker rebuild cycle).

---

## Running tests

```bash
# Unit tests: fast, no Docker needed
cd core
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest tests/pytest/unit -q

# util unit tests
cd ../util
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest tests/ -q
```

Full integration and e2e tests require the Docker compose stack. See [`core/tests/pytest/README.md`](core/tests/pytest/README.md) for the complete testing guide.

---

## Code style

We use [Ruff](https://docs.astral.sh/ruff/) for linting (config in [`ruff.toml`](ruff.toml)). The enforced rules are correctness-focused: pyflakes (`F`), bugbear (`B`), and syntax errors (`E9`), not whitespace/line-length formatting. CI runs `ruff check core/ util/` on every PR.

```bash
pip install ruff==0.15.15
ruff check core/ util/        # lint
ruff check --fix core/ util/  # auto-fix what's safe
```

---

## Key conventions

**Imports inside test functions.** The `core/` unit tests import modules under test *inside* each `def test_...():` body, not at module scope. This is intentional. It lets each test patch `os.environ` before the module resolves its `load_dotenv()` call. Do not move these imports to module scope.

**No hand-authored DDL.** The schema is generated from `schema/fhir.schema.json`. If you need to change which columns a resource table has, modify the schema generation logic in `util/pyfiles/db_handler/resource_schema_generator.py`, not a hand-written column list.

**New cloud provider.** To add AWS, GCP, or another provider, implement the three abstract base classes in `core/pyfiles/adapters/interface.py` (`FHIRServerClient`, `StorageClient`, `ServiceBusMessageQueueClient`) and wire them into `core/main.py`'s dispatch block.

**Tests required.** New code ships with unit tests. Follow the existing fixture and mock patterns in `core/tests/pytest/mocks/`.

---

## Submitting a pull request

For large changes (new adapters, schema-generation changes, new modules), please open a GitHub issue first to discuss the approach before investing significant work.

1. Fork the repo and create a branch. Use a `feat/`, `fix/`, or `docs/` prefix: `git checkout -b feat/my-change`
2. Make your changes with tests.
3. Run unit tests locally (see above). They must pass.
4. Open a PR against `main`. Fill in the PR template.
5. A maintainer will review and respond within a few business days.

**Commit messages** follow a `scope: subject` style, where scope is the area touched (`core:`, `util:`, `ci:`, `docs:`) and the subject is imperative and lower-case:

```
util: fix Linux-incompatible path separators
ci: install pytest for util-unit job
```

---

## Filing a bug

Include:
- FHIR resource type(s) affected
- Mode (`FHIR_SERVICE` / `CLOUD_STORAGE` / `SERVICEBUS` settings)
- Engine version (`SHOW FRONTENDS\G` output)
- A minimal NDJSON sample if the issue is in normalization
- Timing and resource count for performance issues

---

## Security issues

Do not file security vulnerabilities as public issues. See [`SECURITY.md`](SECURITY.md) for the responsible disclosure process.

---

## Code of conduct

All participation in this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant).
