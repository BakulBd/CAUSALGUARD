#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================================="
echo "          Starting CausalGuard Control Center             "
echo "=========================================================="

trap 'kill $(jobs -p) 2>/dev/null || true' EXIT

export CAUSALGUARD_LOG_FORMAT="${CAUSALGUARD_LOG_FORMAT:-console}"
export CAUSALGUARD_ENVIRONMENT="${CAUSALGUARD_ENVIRONMENT:-development}"

echo "Starting Backend API on http://localhost:8000 ..."
# shellcheck disable=SC1091
source .venv/bin/activate
PYTHONPATH=. .venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload &

echo "Waiting for API readiness..."
for _ in {1..40}; do
    if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
        echo "Backend is READY!"
        break
    fi
    sleep 0.5
done

echo "Starting Frontend dev server on http://localhost:5173 ..."
cd "$PROJECT_ROOT/frontend"
if command -v bun >/dev/null 2>&1; then bun run dev -- --host &
elif command -v npm >/dev/null 2>&1; then npm run dev -- --host &
fi

echo "=========================================================="
echo " CausalGuard is running!"
echo " Web UI:     http://localhost:5173"
echo " REST API:   http://localhost:8000/docs"
echo " Health:     http://localhost:8000/ready"
echo " Metrics:    http://localhost:8000/metrics"
echo " Ctrl+C to terminate all services."
echo "=========================================================="
wait
