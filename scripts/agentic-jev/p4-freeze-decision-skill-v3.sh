#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"

V2_ROOT="${AGENTIC_JEV_DECISION_V2_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v2}"
V2_LOCK="$V2_ROOT/runtime-lock.json"
V2_QUAL="$V2_ROOT/activation-qualification-v2/qualification.json"
V2_MANAGER="$V2_ROOT/manager-run/run-manifest.json"

V3_ROOT="${AGENTIC_JEV_DECISION_V3_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v3}"
V3_LOCK="$V3_ROOT/runtime-lock.json"

aj_require_file "$V2_LOCK"
aj_require_file "$V2_QUAL"
aj_require_file "$V2_MANAGER"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$V3_LOCK" "$V2_LOCK" "$V2_QUAL" "$V2_MANAGER" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v3 import (
    create_decision_v3_lock,
)

destination, v2_lock, v2_qual, v2_manager = sys.argv[1:]
result = create_decision_v3_lock(
    destination=Path(destination),
    v2_lock_path=Path(v2_lock),
    v2_qualification_path=Path(v2_qual),
    v2_manager_run_path=Path(v2_manager),
)
print("Agentic Jev decision-skill v3 treatment frozen")
print("v2_manager_jev_calls:", result["parent_v2"]["manager_run_jev_calls"])
print("decision_skill_sha256:", result["skills"]["decision_support_sha256"])
print("decision_skill_interface_sha256:", result["skills"]["decision_support_interface_sha256"])
print("model:", result["runtime"]["model"])
print("codex:", result["runtime"]["codex_version"])
print(result["path"])
PY
