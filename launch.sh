#!/bin/bash
set -e
cd "$(dirname "$0")"

if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Install from: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "First-time setup: configuring paths..."
    echo
    bash scripts/setup_env.sh
    echo
fi

echo "Starting mfethuls Explorer..."
uv run --extra viz streamlit run apps/Home.py
