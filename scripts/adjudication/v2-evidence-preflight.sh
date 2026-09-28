#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_ROOT="$(dirname "$BENCH_REPO")"
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$STACK_ROOT/agent-workflow/.venv/bin/python" ]]; then
  PYTHON="$STACK_ROOT/agent-workflow/.venv/bin/python"
elif [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "$PYTHON" && -x "$PYTHON" ]] || { echo "error: Python not found" >&2; exit 1; }
[[ -n "${V2_ADJUDICATION_MODEL:-}" ]] || {
  echo "error: set V2_ADJUDICATION_MODEL explicitly" >&2
  exit 1
}
MODEL_ARGS_JSON="${V2_ADJUDICATION_MODEL_ARGS_JSON:-{\"responses_api\":true}}"
export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
ROOT="${V2_PREFLIGHT_ROOT:-$DATA_HOME/agent-workflow/routing-semantic-v2-preflight}"
DEST="${V2_PREFLIGHT:-$ROOT/preflight.json}"
force="False"
[[ "${FORCE_V2_PREFLIGHT:-0}" == "1" ]] && force="True"

"$PYTHON" - "$DEST" "$V2_ADJUDICATION_MODEL" "$MODEL_ARGS_JSON" "$force" <<'PY'
import json
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.inspect_adjudication import (
    resolve_latest_codex_cli,
    run_v2_evidence_preflight,
)

destination, model, args_json, force = sys.argv[1:]
args = json.loads(args_json)
if not isinstance(args, dict):
    raise SystemExit("V2_ADJUDICATION_MODEL_ARGS_JSON must decode to an object")
codex = resolve_latest_codex_cli()
result = run_v2_evidence_preflight(
    destination=Path(destination),
    codex_version=codex["resolved"],
    model=model,
    model_args=args,
    force=(force == "True"),
)
print("routing-semantic-v2 evidence preflight: PASS")
for gate, evidence in result["gates"].items():
    print(gate, evidence["status"])
print("real_cohort_ready:", result["real_cohort_ready"])
print("blocking_reason:", result["blocking_reason"])
print(result["path"])
PY
