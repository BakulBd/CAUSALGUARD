#!/usr/bin/env bash
# End-to-end smoke test against a running CausalGuard API.
set -euo pipefail
BASE="${CAUSALGUARD_BASE:-http://localhost:8000}"
KEY_HEADER=()
[[ -n "${CAUSALGUARD_API_KEY:-}" ]] && KEY_HEADER=(-H "Authorization: Bearer ${CAUSALGUARD_API_KEY}")

say() { printf '\n\033[1;36m== %s\033[0m\n' "$1"; }
req() { curl -fsS "${KEY_HEADER[@]}" "$@"; }

say "health";        req "$BASE/health" | head -c 400; echo
say "ready";         req "$BASE/ready" | head -c 600; echo
say "metrics (head)"; req "$BASE/metrics" | grep -E '^causalguard_' | head -n 6
say "telemetry-status"; req "$BASE/api/v1/system/telemetry-status"; echo
say "start scenario pg-lock-contention"; req -X POST "$BASE/api/v1/scenarios/pg-lock-contention/start"; echo
say "system state";  req "$BASE/api/v1/system/state"; echo
say "run investigation"; req -X POST "$BASE/api/v1/investigations" | python3 -m json.tool | head -n 40
say "list risks";    req "$BASE/api/v1/risks"; echo
say "verify intervention"; req -X POST "$BASE/api/v1/risks/current/verify-intervention" | python3 -m json.tool | head -n 20
say "stop scenario"; req -X POST "$BASE/api/v1/scenarios/pg-lock-contention/stop"; echo
say "OK"
