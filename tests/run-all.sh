#!/usr/bin/env bash
# run-all.sh — full test run: unit + regression (fast) and integration
# (real Docker + dbctl-sandbox; skipped automatically when unavailable).
set -euo pipefail
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.."

echo "== unit + regression =="
.venv/bin/pytest tests/unit -q

echo
echo "== integration (Docker + dbctl-sandbox; skip se indisponível) =="
.venv/bin/pytest tests/integration -v
