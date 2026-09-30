#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"

V3_ROOT="${AGENTIC_JEV_DECISION_V3_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v3}"
V3_LOCK="$V3_ROOT/runtime-lock.json"
QUALIFICATION="$V3_ROOT/activation-qualification/qualification.json"
CANARY_ROOT="$V3_ROOT/manager-canary"

aj_require_file "$V3_LOCK"
aj_require_file "$QUALIFICATION"
[[ -d "$CHECKOUT/.git" ]] || aj_die "missing pinned Inspect Evals checkout: $CHECKOUT"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$CANARY_ROOT" "$V3_LOCK" "$QUALIFICATION" "$CHECKOUT" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v3 import (
    run_decision_v3_manager_canary,
)

root, lock, qualification, checkout = sys.argv[1:]
result = run_decision_v3_manager_canary(
    output_root=Path(root),
    v3_lock_path=Path(lock),
    activation_qualification_path=Path(qualification),
    inspect_evals_checkout=Path(checkout),
)
execution = result["execution"]
print("Agentic Jev decision-skill v3 manager canary: PASS")
print("samples:", execution["samples_observed"])
print("success:", execution["success"])
print("errors:", execution["errors"])
print("jev_calls:", execution["jev_tool_calls"])
print("samples_with_jev_calls:", execution["samples_with_jev_calls"])
print("gate:", result["gate"])
print(result["path"])
PY
