#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "Resetting CausalGuard environment..."
curl -s -X POST http://localhost:8000/api/scenarios/pg-table-bloat/stop >/dev/null 2>&1 || true
source .venv/bin/activate
PYTHONPATH=. .venv/bin/python -c "
from backend.storage.observation_store import global_observation_store
from backend.scenarios.scenario_manager import scenario_manager
global_observation_store.clear()
scenario_manager.stop_scenario()
print('Environment reset cleanly to healthy baseline.')
"
