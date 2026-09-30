#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"

V2_ROOT="${AGENTIC_JEV_DECISION_V2_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v2}"
MANAGER_ROOT="$V2_ROOT/manager-run"

aj_require_file "$MANAGER_ROOT/run-manifest.json"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}"   "$PYTHON" "$SCRIPT_DIR/p4-audit-v2-manager-traces.py" "$MANAGER_ROOT"
