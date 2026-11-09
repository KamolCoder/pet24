#!/usr/bin/env bash
# Full local gate: lint, migrations, API schema, tests. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python
[ -x .venv/bin/python ] && PY=.venv/bin/python

echo "== ruff"
"$PY" -m ruff check .
echo "== migrations up to date"
DEBUG=1 "$PY" manage.py makemigrations --check --dry-run
echo "== OpenAPI schema (warnings fail)"
DEBUG=1 "$PY" manage.py spectacular --fail-on-warn --file /dev/null
echo "== tests"
"$PY" manage.py test "$@"
echo "ALL GREEN"
