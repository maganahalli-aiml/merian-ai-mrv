#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
uv run python -m uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8080