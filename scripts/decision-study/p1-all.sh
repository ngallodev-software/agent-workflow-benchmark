#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "P1/3 — prepare deterministic development-only smoke corpus"
bash "$SCRIPT_DIR/p1-prepare-smoke.sh"

echo
echo "P1/3 — run live comparative instrumentation smoke"
bash "$SCRIPT_DIR/p1-run-smoke.sh"

echo
echo "P1/3 — verify persisted evidence invariants"
bash "$SCRIPT_DIR/p1-verify-smoke.sh"

echo
echo "P1 complete. Do not interpret this below-threshold smoke as comparative effectiveness evidence."
