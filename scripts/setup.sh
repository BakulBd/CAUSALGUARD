#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "           CausalGuard Environment Setup                  "
echo "  Predict. Simulate. Verify. Prevent. (AMD ROCm)          "
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "[1/5] Checking AMD GPU & ROCm KFD nodes..."
if [ -e /dev/kfd ]; then
    echo "  -> Found /dev/kfd (AMD Kernel Fusion Driver is ACTIVE)"
else
    echo "  -> Note: /dev/kfd not detected. Running with host DRM sysfs emulation."
fi
[ -e /dev/dri/renderD128 ] && echo "  -> Found /dev/dri/renderD128 (Direct Rendering Node available)"

echo "[2/5] Creating Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev,postgres]"

echo "[3/5] Seeding local configuration..."
[ -f .env ] || { cp .env.example .env; echo "  -> wrote .env from .env.example"; }

echo "[4/5] Installing frontend dependencies..."
cd "$PROJECT_ROOT/frontend"
if command -v bun >/dev/null 2>&1; then bun install
elif command -v pnpm >/dev/null 2>&1; then pnpm install
elif command -v npm >/dev/null 2>&1; then npm install
fi
cd "$PROJECT_ROOT"

echo "[5/5] Verifying installation (lint + tests)..."
.venv/bin/ruff check backend
PYTHONPATH=. .venv/bin/pytest -q

echo "=========================================================="
echo " Setup complete!  Start CausalGuard with: ./scripts/start_lab.sh"
echo " Or the full container stack with:         make up"
echo "=========================================================="
