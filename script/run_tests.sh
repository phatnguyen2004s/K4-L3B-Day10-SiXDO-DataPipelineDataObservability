#!/usr/bin/env bash
# One-click test: cai dev deps va chay pytest + coverage (fail neu coverage < 80%).
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  uv sync --extra dev
  uv run python -m pytest --cov-fail-under=80 "$@"
else
  python -m pip install -e ".[dev]"
  python -m pytest --cov-fail-under=80 "$@"
fi
