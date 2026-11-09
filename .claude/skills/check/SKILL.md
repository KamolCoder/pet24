---
name: check
description: Run the full backend quality gate for Pet24 (ruff, migrations check, OpenAPI schema, Django tests) and fix failures. Use before every commit, after changing backend code, or when the user says "проверь", "check", "прогони тесты".
---

# Backend quality gate

1. From `backend/`, run `scripts/check.sh` (it picks `.venv/bin/python` when present).
   Pass extra args to limit tests, e.g. `scripts/check.sh tests.test_panel`.
2. If a step fails, fix the cause, not the check:
   - **ruff** — `python -m ruff check . --fix` for safe fixes, then fix the rest by hand. Config is in `backend/pyproject.toml`.
   - **migrations** — a model changed without a migration: `DEBUG=1 python manage.py makemigrations <app>` and commit it.
   - **OpenAPI** — add `@extend_schema` / type hints on serializer methods so the schema has no warnings
     (the Flutter client is generated from it).
   - **tests** — never skip or delete a failing test to get green; reproduce, fix the code, re-run.
3. Re-run `scripts/check.sh` until it prints `ALL GREEN`. Report the test count to the user.
