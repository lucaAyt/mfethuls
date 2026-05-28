#!/usr/bin/env bash
set -euo pipefail

mode="${1:-api}"

if [[ "$mode" == "api" ]]; then
  exec python scripts/run_api.py
elif [[ "$mode" == "worker" ]]; then
  exec python scripts/run_worker.py
else
  echo "Unknown mode: $mode (expected: api | worker)" >&2
  exit 1
fi
