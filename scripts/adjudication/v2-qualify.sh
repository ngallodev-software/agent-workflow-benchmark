#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_ROOT="$(dirname "$BENCH_REPO")"

AW="${AW:-}"
if [[ -z "$AW" && -x "$STACK_ROOT/agent-workflow/.venv/bin/agent-workflow" ]]; then
  AW="$STACK_ROOT/agent-workflow/.venv/bin/agent-workflow"
elif [[ -z "$AW" ]]; then
  AW="$(command -v agent-workflow || true)"
fi

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$STACK_ROOT/agent-workflow/.venv/bin/python" ]]; then
  PYTHON="$STACK_ROOT/agent-workflow/.venv/bin/python"
elif [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi

[[ -n "$AW" && -x "$AW" ]] || { echo "error: Agent-Workflow launcher not found" >&2; exit 1; }
[[ -n "$PYTHON" && -x "$PYTHON" ]] || { echo "error: Python not found" >&2; exit 1; }

export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

MODEL="${V2_ADJUDICATION_MODEL:-openai-api/codex-lb/deepseek-flash}"
if [[ "$MODEL" != "openai-api/codex-lb/deepseek-flash" ]]; then
  echo "error: routing-semantic-v2 qualification model is frozen to openai-api/codex-lb/deepseek-flash" >&2
  exit 1
fi

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PRIVATE_ROOT="${V2_QUALIFICATION_ROOT:-$DATA_HOME/agent-workflow/routing-semantic-v2-qualification}"
MODULE="${V2_MODULE:-$BENCH_REPO/modules/abc-adjudication/routing-semantic-v2.inspect.module.json}"
RUNTIME_LOCK="${V2_RUNTIME_LOCK:-$PRIVATE_ROOT/runtime-lock.json}"
QUALIFICATION="${V2_QUALIFICATION:-$PRIVATE_ROOT/qualification.json}"
RUN_LOG="$PRIVATE_ROOT/qualification-run.log"
ATTEMPT_META="$PRIVATE_ROOT/attempt.json"
DIAGNOSE="$SCRIPT_DIR/v2-diagnose.py"

[[ -f "$MODULE" ]] || { echo "error: v2 Inspect module not found: $MODULE" >&2; exit 1; }

"$PYTHON" - <<'PY'
from importlib import metadata

expected = {
    "agent-workflow-benchmark": "0.6.3",
    "agent-workflow-comparative-eval": "0.3.1",
}
for name, wanted in expected.items():
    observed = metadata.version(name)
    if observed != wanted:
        raise SystemExit(f"{name} {observed} installed; expected {wanted}")
PY

mkdir -p "$PRIVATE_ROOT"
retry_root=""

if [[ -f "$QUALIFICATION" || -d "$PRIVATE_ROOT/inspect-qualification" || -f "$RUN_LOG" || -f "$ATTEMPT_META" ]]; then
  if [[ "${FORCE_V2_QUALIFICATION:-0}" != "1" ]]; then
    echo "error: v2 qualification evidence already exists; preserve it or set FORCE_V2_QUALIFICATION=1 for an archived retry" >&2
    echo "qualification: $QUALIFICATION" >&2
    exit 1
  fi
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  retry_root="$PRIVATE_ROOT/retries/$stamp"
  mkdir -p "$retry_root"
  [[ ! -f "$QUALIFICATION" ]] || mv "$QUALIFICATION" "$retry_root/qualification.json"
  [[ ! -d "$PRIVATE_ROOT/inspect-qualification" ]] || mv "$PRIVATE_ROOT/inspect-qualification" "$retry_root/inspect-qualification"
  [[ ! -f "$RUN_LOG" ]] || mv "$RUN_LOG" "$retry_root/qualification-run.log"
  [[ ! -f "$ATTEMPT_META" ]] || mv "$ATTEMPT_META" "$retry_root/attempt.json"
  echo "Archived prior qualification attempt: $retry_root"
fi

runtime_lock_valid=0
if [[ -f "$RUNTIME_LOCK" ]]; then
  if "$PYTHON" - "$MODULE" "$RUNTIME_LOCK" <<'PY'
import sys
from pathlib import Path

from agent_workflow_benchmark.benchmarking.adjudication_module import (
    validate_abc_adjudication_module,
)
from agent_workflow_benchmark.benchmarking.inspect_adjudication import (
    _load_runtime_lock,
)

module_path, runtime_lock_path = map(Path, sys.argv[1:3])
module = validate_abc_adjudication_module(module_path)
_load_runtime_lock(runtime_lock_path, module)
PY
  then
    runtime_lock_valid=1
    echo "Reusing frozen v2 runtime lock: $RUNTIME_LOCK"
  else
    if [[ "${FORCE_V2_QUALIFICATION:-0}" != "1" ]]; then
      echo "error: existing v2 runtime lock is incompatible with the strengthened structured-output runtime; set FORCE_V2_QUALIFICATION=1 to archive it and freeze a new lock" >&2
      exit 1
    fi
    if [[ -z "$retry_root" ]]; then
      stamp="$(date -u +%Y%m%dT%H%M%SZ)"
      retry_root="$PRIVATE_ROOT/retries/$stamp"
      mkdir -p "$retry_root"
    fi
    mv "$RUNTIME_LOCK" "$retry_root/runtime-lock.json"
    echo "Archived incompatible runtime lock: $retry_root/runtime-lock.json"
  fi
fi

if [[ "$runtime_lock_valid" != "1" ]]; then
  "$AW" benchmark adjudication-inspect-runtime-lock \
    "$MODULE" \
    "$RUNTIME_LOCK"
fi

attempt_id="$(date -u +%Y%m%dT%H%M%SZ)"
"$PYTHON" - "$ATTEMPT_META" "$attempt_id" "$MODEL" "${V2_LOG_MODEL_API:-0}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
record = {
    "attempt_id": sys.argv[2],
    "model": sys.argv[3],
    "log_model_api": sys.argv[4] == "1",
    "status": "running",
}
path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

qualify_args=()
if [[ "${V2_LOG_MODEL_API:-0}" == "1" ]]; then
  qualify_args+=(--log-model-api)
  echo "Model-API evidence capture: enabled (private log only)"
fi

echo "Qualification evidence: $PRIVATE_ROOT/inspect-qualification"
echo "Private run log: $RUN_LOG"

set +e
"$AW" benchmark adjudication-inspect-qualify-live \
  "$MODULE" \
  "$RUNTIME_LOCK" \
  "$QUALIFICATION" \
  --model "$MODEL" \
  --model-arg responses_api=true \
  "${qualify_args[@]}" \
  >"$RUN_LOG" 2>&1
qualify_status=$?
set -e

if [[ "$qualify_status" != "0" ]]; then
  "$PYTHON" - "$ATTEMPT_META" "$qualify_status" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
record = json.loads(path.read_text(encoding="utf-8"))
record["status"] = "failed"
record["exit_status"] = int(sys.argv[2])
path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "routing-semantic-v2 full qualification: FAIL"
  echo "Agent-Workflow exit status: $qualify_status"
  "$PYTHON" "$DIAGNOSE" --root "$PRIVATE_ROOT" --attempt current || true
  echo "Full private output retained at: $RUN_LOG"
  exit "$qualify_status"
fi

"$PYTHON" - "$ATTEMPT_META" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
record = json.loads(path.read_text(encoding="utf-8"))
record["status"] = "command-complete"
path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

"$PYTHON" - "$QUALIFICATION" "$MODULE" "$RUNTIME_LOCK" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from agent_workflow_benchmark.benchmarking.adjudication_module import (
    validate_abc_adjudication_module,
)
from agent_workflow_benchmark.benchmarking.schema_contracts import validate_instance

qualification_path, module_path, runtime_lock_path = map(Path, sys.argv[1:4])

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
validate_instance(
    qualification,
    "agent-workflow-benchmark/inspect-adjudication-qualification/v2",
    artifact=str(qualification_path),
)
if qualification.get("qualified") is not True:
    raise SystemExit("routing-semantic-v2 full qualification did not pass")

gates = qualification.get("gates") or {}
required = [f"IA-{number}" for number in range(1, 12)]
failed = [
    gate for gate in required
    if (gates.get(gate) or {}).get("status") != "pass"
]
if failed:
    raise SystemExit(f"routing-semantic-v2 qualification has non-passing gates: {failed}")

module = validate_abc_adjudication_module(module_path)
if qualification.get("module_sha256") != module["module_sha256"]:
    raise SystemExit("qualification module hash does not match frozen v2 module")
if qualification.get("runtime_lock_sha256") != sha256(runtime_lock_path):
    raise SystemExit("qualification runtime-lock hash does not match frozen runtime")

print("routing-semantic-v2 full qualification: PASS")
for gate in required:
    print(gate, gates[gate]["status"])
print("qualified:", qualification["qualified"])
print("runtime_lock:", runtime_lock_path)
print("qualification:", qualification_path)
PY
