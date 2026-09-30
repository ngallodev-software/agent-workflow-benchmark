#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

V2_ROOT="${AGENTIC_JEV_DECISION_V2_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v2}"
V2_LOCK="$V2_ROOT/runtime-lock.json"
QUAL_ROOT="$V2_ROOT/activation-qualification-v2"

aj_require_file "$V2_LOCK"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$QUAL_ROOT"   "$V2_LOCK" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v2 import (
    run_decision_v2_activation_qualification,
)

root, lock = sys.argv[1:]
result = run_decision_v2_activation_qualification(
    output_root=Path(root),
    v2_lock_path=Path(lock),
)
print("Agentic Jev decision-skill v2 activation qualification protocol v2: PASS")
print(
    "control_jev_calls:",
    result["control"]["jev_tool_calls"],
    "treatment_jev_calls:",
    result["treatment"]["jev_tool_calls"],
)
print("activation_protocol:", result["activation_protocol"])\nprint("activation_lift_observed:", result["activation_lift_observed"])
print(result["path"])
PY
