#!/usr/bin/env bash
set -e

SCENARIO="${1:-pg-table-bloat}"
ACTION="${2:-start}"

API_URL="http://localhost:8000"

if [ "$ACTION" == "start" ]; then
    echo "Triggering reliability scenario: $SCENARIO..."
    curl -s -X POST "$API_URL/api/scenarios/$SCENARIO/start" | python3 -m json.tool
elif [ "$ACTION" == "stop" ]; then
    echo "Stopping scenario..."
    curl -s -X POST "$API_URL/api/scenarios/$SCENARIO/stop" | python3 -m json.tool
elif [ "$ACTION" == "investigate" ]; then
    echo "Triggering closed-loop investigation..."
    curl -s -X POST "$API_URL/api/investigations" | python3 -m json.tool
else
    echo "Usage: ./scripts/run_scenario.sh [pg-table-bloat|pg-lock-contention] [start|stop|investigate]"
fi
