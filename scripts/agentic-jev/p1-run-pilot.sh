#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_RUNTIME_LOCK"
aj_require_file "$AGENTIC_JEV_QUALIFICATION"
aj_require_typesafe_key

force="False"
[[ "${FORCE_AGENTIC_JEV_PILOT:-0}" == "1" ]] && force="True"

"$PYTHON" - "$AGENTIC_JEV_RUN" "$AGENTIC_JEV_RUNTIME_LOCK" "$AGENTIC_JEV_QUALIFICATION" "$force" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev import run_agentic_jev_pilot

root, lock, qualification, force = sys.argv[1:]
result = run_agentic_jev_pilot(
    output_root=Path(root),
    runtime_lock_path=Path(lock),
    qualification_path=Path(qualification),
    force=(force == "True"),
)
print("Agent-directed Jev pilot complete (development-only; no effectiveness claim)")
for arm_id, arm in result["arms"].items():
    print(
        arm_id,
        "samples=", arm["samples"],
        "success=", arm["sample_status"]["success"],
        "errors=", arm["sample_status"]["error"],
        "jev_calls=", arm["jev_tool_calls"],
    )
print(result["path"])
PY
