#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

V3_ROOT="${AGENTIC_JEV_DECISION_V3_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v3}"
V3_LOCK="$V3_ROOT/runtime-lock.json"
QUAL_ROOT="$V3_ROOT/activation-qualification"

aj_require_file "$V3_LOCK"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$QUAL_ROOT" "$V3_LOCK" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v3 import (
    run_decision_v3_activation_qualification,
)

root, lock = sys.argv[1:]
result = run_decision_v3_activation_qualification(
    output_root=Path(root),
    v3_lock_path=Path(lock),
)
print("Agentic Jev decision-skill v3 second-order activation qualification: PASS")
print("control_jev_calls:", result["control"]["jev_tool_calls"])
print("treatment_jev_calls:", result["treatment"]["jev_tool_calls"])
print("treatment_second_order_primitives:", result["treatment"]["second_order_primitives"])
print("activation_lift_observed:", result["activation_lift_observed"])
print("activation_protocol:", result["activation_protocol"])
print(result["path"])
PY
