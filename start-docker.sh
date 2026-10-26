#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or is not available on PATH." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env file. Copy .env.example to .env and add your settings first." >&2
  exit 1
fi

docker build -t meridian-ai .
exec docker run --rm \
  --name meridian-ai-local \
  -p 8080:8080 \
  --env-file .env \
  -v meridian-data:/app/.meridian \
  meridian-ai
