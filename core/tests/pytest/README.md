# hyperion-core tests

Pytest suite for `hyperion-core`. Unit tests are fast and fully mocked (no Docker);
integration and e2e tests boot the Docker stack via fixtures.

## Quick start

Run from the `core/` directory:

```bash
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest tests/pytest/unit -q          # fast, no external services
```

Coverage:

```bash
PYTHONPATH=. pytest tests/pytest/unit --cov=pyfiles --cov-report=html
# open htmlcov/index.html
```

## Layout

```
tests/pytest/
├── conftest.py        # shared fixtures (schema, sample NDJSON, mock configs)
├── unit/              # mock everything — dependencies/, hyperion_core/, adapters/
├── integration/       # require Docker (engine, HAPI) via fixtures
├── e2e/               # full pipeline end-to-end
├── regression/        # known-issue guards
├── mocks/             # reusable fakes (queue, storage, StarRocks, FHIR)
└── test_data/         # synthetic FHIR fixtures (Synthea-style)
```

## Running subsets

```bash
PYTHONPATH=. pytest tests/pytest/unit/dependencies/test_df_ops.py -q   # one file
PYTHONPATH=. pytest tests/pytest/unit -k "normalizer" -q              # by keyword
PYTHONPATH=. pytest tests/pytest/unit -m "not slow" -q                # by marker
```

Integration / e2e require the compose stack (see the repo `README.md` quickstart) and
are correspondingly slower.

## Conventions

- **Imports inside test functions.** `unit/` tests import the module under test *inside*
  each `def test_...()` so `os.environ` can be patched before the module resolves its
  `load_dotenv()` call. Don't hoist these to module scope.
- **Mocks live in `mocks/`.** Reuse the existing Azure / StarRocks / FHIR fakes rather
  than re-rolling per test; follow the fixture patterns in `conftest.py`.
- **New code ships with unit tests.** Match the existing arrange/act/assert style.

## CI

`.github/workflows/test.yml` runs the unit suites (core + util), the lint job (ruff),
and a Docker build check on every push and PR.

## Troubleshooting

- **Import errors** — run from `core/` with `PYTHONPATH=.` (or from the repo root with
  `PYTHONPATH=core pytest core/tests/pytest/unit`).
- **Discovery** — files `test_*.py`, classes `Test*`, functions `test_*`.
