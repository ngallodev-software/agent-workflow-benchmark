#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

MODEL="${AGENTIC_JEV_CURRENT_MODEL:-openai-api/codex-lb/gpt-6-luna}"
EFFORT="${AGENTIC_JEV_CURRENT_REASONING_EFFORT:-high}"
MODEL_SLUG="${MODEL##*/}"
OUT_ROOT="${AGENTIC_JEV_CURRENT_QUAL_ROOT:-$AGENTIC_JEV_ROOT/current-model-qualification/$MODEL_SLUG}"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - \
  "$OUT_ROOT" "$MODEL" "$EFFORT" "${AGENTIC_JEV_JEV_MODEL:-}" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_current_model import (
    run_current_model_qualification,
)

root, model, effort, jev_model = sys.argv[1:]
result = run_current_model_qualification(
    output_root=Path(root),
    model=model,
    reasoning_effort=effort,
    jev_model=jev_model or None,
)
print("Current-model Jev context/rationale qualification: PASS")
print("model:", result["runtime"]["model"])
print("jev_tool_calls:", result["jev_execution"]["tool_calls"])
print("successful_jev_calls:", result["jev_execution"]["successful_calls"])
print("checks:", result["checks"])
print("decision_record:", result["decision_record"])
print("artifact:", result["path"])
PY
