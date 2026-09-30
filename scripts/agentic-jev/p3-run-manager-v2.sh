#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"
V2_ROOT="${AGENTIC_JEV_DECISION_V2_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v2}"
V2_LOCK="$V2_ROOT/runtime-lock.json"
QUALIFICATION="$V2_ROOT/activation-qualification-v2/qualification.json"
RUN_ROOT="$V2_ROOT/manager-run"

aj_require_file "$V2_LOCK"
aj_require_file "$QUALIFICATION"
[[ -d "$CHECKOUT/.git" ]] || aj_die "missing pinned Inspect Evals checkout: $CHECKOUT"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$RUN_ROOT"   "$V2_LOCK"   "$QUALIFICATION"   "$CHECKOUT" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v2 import (
    run_decision_v2_manager_gate,
)

run_root, lock, qualification, checkout = sys.argv[1:]
result = run_decision_v2_manager_gate(
    output_root=Path(run_root),
    v2_lock_path=Path(lock),
    activation_qualification_path=Path(qualification),
    inspect_evals_checkout=Path(checkout),
)
execution = result["execution"]
print("Agentic Jev decision-skill v2 manager gate complete")
print("samples:", execution["samples_observed"])
print("success:", execution["success"])
print("errors:", execution["errors"])
print("jev_calls:", execution["jev_tool_calls"])
print("samples_with_jev_calls:", execution["samples_with_jev_calls"])
print(result["path"])
PY
