#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_TASKS"
aj_require_model

force="False"
[[ "${FORCE_RUNTIME_LOCK:-0}" == "1" ]] && force="True"

"$PYTHON" - "$AGENTIC_JEV_TASKS" "$AGENTIC_JEV_RUNTIME_LOCK" "$AGENTIC_JEV_MODEL" "$AGENTIC_JEV_REASONING_EFFORT" "$AGENTIC_JEV_MODEL_ARGS_JSON" "$AGENTIC_JEV_JEV_MODEL" "$force" <<'PY'
import json
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev import create_agentic_jev_runtime_lock

tasks, destination, model, reasoning_effort, args_json, jev_model, force = sys.argv[1:]
args = json.loads(args_json)
if not isinstance(args, dict):
    raise SystemExit("AGENTIC_JEV_MODEL_ARGS_JSON must decode to a JSON object")
result = create_agentic_jev_runtime_lock(
    destination=Path(destination),
    tasks_path=Path(tasks),
    agent_model=model,
    agent_reasoning_effort=reasoning_effort,
    agent_model_args=args,
    jev_model=jev_model or None,
    force=(force == "True"),
)
print("Agentic Jev runtime frozen")
print("codex:", result["codex_cli"]["resolved"])
print("model:", result["agent_model"])
print("reasoning_effort:", result["agent_reasoning_effort"])
print("skill_sha256:", result["skill"]["sha256"])
print("tasks_sha256:", result["tasks"]["sha256"])
print("runtime_lock_sha256:", result["sha256"])
print(result["path"])
PY
