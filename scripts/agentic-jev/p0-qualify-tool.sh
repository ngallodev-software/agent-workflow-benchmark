#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_RUNTIME_LOCK"
aj_require_typesafe_key

force="False"
[[ "${FORCE_JEV_QUALIFY:-0}" == "1" ]] && force="True"

"$PYTHON" - "$AGENTIC_JEV_QUAL_ROOT" "$AGENTIC_JEV_RUNTIME_LOCK" "$force" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev import run_agentic_jev_tool_qualification

root, lock, force = sys.argv[1:]
result = run_agentic_jev_tool_qualification(
    output_root=Path(root),
    runtime_lock_path=Path(lock),
    force=(force == "True"),
)
print("Agent-directed Jev tool qualification: PASS")
print("model:", result["model"])
print("reasoning_effort:", result["reasoning_effort"])
print("codex:", result["codex_version"])
print("skill_sha256:", result["skill_sha256"])
print("receipt_summary:", result["receipt_summary"])
print(result["path"])
PY
