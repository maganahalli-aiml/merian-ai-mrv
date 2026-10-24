#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
uv run python -m uvicorn api.main:app --app-dir backend --reload --host 0.0.0.0 --port 8080