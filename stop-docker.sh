#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or is not available on PATH." >&2
  exit 1
fi

if ! running="$(docker container inspect --format '{{.State.Running}}' meridian-ai-local 2>/dev/null)"; then
  echo "Docker container meridian-ai-local is not running."
  exit 0
fi

if [[ "$running" != "true" ]]; then
  echo "Docker container meridian-ai-local is not running."
  exit 0
fi

docker stop meridian-ai-local
