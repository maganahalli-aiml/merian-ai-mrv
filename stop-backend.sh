#!/usr/bin/env bash
set -euo pipefail

pattern='uvicorn api\.main:app --app-dir backend .*--port 8080'
mapfile -t pids < <(pgrep -f "$pattern" || true)

if ((${#pids[@]} == 0)); then
    echo "Backend is not running on port 8080."
    exit 0
fi

for pid in "${pids[@]}"; do
    kill -TERM "$pid"
done

for _ in {1..50}; do
    mapfile -t remaining < <(pgrep -f "$pattern" || true)
    if ((${#remaining[@]} == 0)); then
        echo "Backend stopped."
        exit 0
    fi
    sleep 0.1
done

echo "Backend did not stop cleanly. Remaining PIDs: ${remaining[*]}" >&2
exit 1
