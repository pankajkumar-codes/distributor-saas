# Planted CI fixtures (AC-13)

Each folder holds code a CI check must reject. `tests/tools/test_ci_checks.py` runs
each check on its fixture and expects it to fail with the listed findings, then runs
it on the repository and expects it to pass. Nothing here is imported or deployed.

- `migrations/`: `python -m migrator.checks` (the `migrations` job).
- `tax_literals/`: `scripts/ci_checks/tax_literals.py` (the `tax-literals` job).
- `sql_boundaries/`: `scripts/ci_checks/sql_boundaries.py` (the `boundaries` job).
- `clock/`: ruff's TID251 clock rule (the `lint` job). `tests/**` is exempt from the
  rule in ruff.toml, so the test copies the file out before checking it.
