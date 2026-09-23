#!/usr/bin/env bash
set -euo pipefail

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
AGENT_CLASS="${AGENT_CLASS:-implementation}"
REPETITIONS="${BM6_REPETITIONS:-1}"
ROOT_ARG=""

usage() {
  cat <<'USAGE'
Usage: scripts/run-bm6-blind.sh [options]

Run BM6 only through paired execution and cryptographic execution sealing.

Task:
  Change Window Planner v1
Treatments:
  structured-direct/v1 vs agent-workflow-bm5/v1
Model:
  gpt-6-luna, high reasoning

The execution suite contains no reference solution and no local hidden evaluator.
The script intentionally stops after execution-seal verification. Scoring, visual
capture, consolidation, and reporting are separate post-seal operations.

Options:
  --root PATH          durable BM6 artifact root
  --repetitions N      paired repetitions (default: BM6_REPETITIONS or 1)
  --agent-class NAME   Agent-Workflow candidate class
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      shift; [[ $# -gt 0 ]] || { echo "--root requires a value" >&2; exit 2; }
      ROOT_ARG="$1"
      ;;
    --repetitions)
      shift; [[ $# -gt 0 ]] || { echo "--repetitions requires a value" >&2; exit 2; }
      REPETITIONS="$1"
      ;;
    --agent-class)
      shift; [[ $# -gt 0 ]] || { echo "--agent-class requires a value" >&2; exit 2; }
      AGENT_CLASS="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ "$REPETITIONS" =~ ^[1-9][0-9]*$ ]] || {
  echo "repetitions must be a positive integer: $REPETITIONS" >&2
  exit 2
}

if [[ "$AW_BIN" == */* ]]; then
  AW_PATH="$(python3 - "$AW_BIN" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
else
  AW_PATH="$(command -v "$AW_BIN" 2>/dev/null || true)"
fi
[[ -n "$AW_PATH" ]] || { echo "Agent-Workflow launcher not found: $AW_BIN" >&2; exit 1; }

if [[ -n "${AGENT_WORKFLOW_VENV:-}" ]]; then
  DEV_VENV="$(python3 - "$AGENT_WORKFLOW_VENV" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  DEV_VENV="$(python3 - "$VIRTUAL_ENV" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
else
  DEV_VENV="$(dirname "$(dirname "$AW_PATH")")"
fi

if [[ -x "$DEV_VENV/bin/python" ]]; then
  PYTHON="$DEV_VENV/bin/python"
elif [[ -x "$DEV_VENV/bin/python3" ]]; then
  PYTHON="$DEV_VENV/bin/python3"
else
  echo "shared Agent-Workflow virtualenv has no Python: $DEV_VENV" >&2
  exit 1
fi

export VIRTUAL_ENV="$DEV_VENV"
export AGENT_WORKFLOW_VENV="$DEV_VENV"
export AGENT_WORKFLOW_BIN="$DEV_VENV/bin/agent-workflow"
export PATH="$DEV_VENV/bin:$PATH"
export XDG_CONFIG_HOME="$DEV_VENV/.xdg/config"
export XDG_STATE_HOME="$DEV_VENV/.xdg/state"
export XDG_DATA_HOME="$DEV_VENV/.xdg/data"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_DATA_HOME"
AW_BIN="$AGENT_WORKFLOW_BIN"

"$PYTHON" - <<'PY'
from importlib import metadata
required = {
    "agent-workflow": "0.11.9",
    "agent-workflow-benchmark": "0.3.9",
}
for name, expected in required.items():
    observed = metadata.version(name)
    if observed != expected:
        raise SystemExit(f"{name}={observed}; BM6 requires {expected}")
PY

ROOT="${ROOT_ARG:-${BM6_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-bm6.XXXXXX")}}"
SUITE="$ROOT/suite"
FIXTURE="$ROOT/fixture"
READINESS_JSON="$ROOT/readiness.json"
PLAN_JSON="$ROOT/plan.json"
RUN_JSON="$ROOT/run.json"
SEAL_JSON="$ROOT/execution-seal-command.json"
SEAL_VERIFY_JSON="$ROOT/execution-seal-verify.json"

mkdir -p "$ROOT"

echo "BM6 root: $ROOT"
echo "task: Change Window Planner v1"
echo "comparison: structured-direct/v1 vs agent-workflow-bm5/v1"
echo "repetitions: $REPETITIONS"

"$AW_BIN" benchmark bm6-export "$SUITE" --agent-class "$AGENT_CLASS"

"$PYTHON" - "$SUITE" <<'PY'
import json
import sys
from pathlib import Path

suite = Path(sys.argv[1])
contract = json.loads((suite / "scoring-contract.json").read_text(encoding="utf-8"))
for forbidden in (suite / "evaluation", suite / "executors" / "solutions"):
    if forbidden.exists():
        raise SystemExit(f"blind-suite violation: {forbidden}")
if list(suite.rglob("score.py")):
    raise SystemExit("blind-suite violation: local score.py found")
if contract.get("evaluator_path") != "external://score.py":
    raise SystemExit(f"unexpected evaluator ref: {contract.get('evaluator_path')!r}")
print("blind-suite preflight: no local evaluator or reference solution")
PY

"$AW_BIN" benchmark fixture-create "$SUITE/benchmark-spec.json" "$FIXTURE"

EXECUTOR="$SUITE/executors/codex-subscription.json"
POLICY="$SUITE/policies/development.json"

"$AW_BIN" --json benchmark readiness "$SUITE/benchmark-spec.json"   --executor "$EXECUTOR"   --policy "$POLICY"   --execution-only > "$READINESS_JSON"

"$PYTHON" - "$READINESS_JSON" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("ready") is not True:
    for check in value.get("checks", []):
        if not check.get("passed"):
            print(f"{check.get('id')}: {check.get('detail')}", file=sys.stderr)
    raise SystemExit("BM6 execution readiness failed")
print("BM6 execution readiness: passed")
PY

"$AW_BIN" --json benchmark plan "$SUITE/benchmark-spec.json"   --repo "$FIXTURE"   --base-ref HEAD   --executor "$EXECUTOR"   --policy "$POLICY"   --repetitions "$REPETITIONS" > "$PLAN_JSON"

RUN_PLAN="$("$PYTHON" - "$PLAN_JSON" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_plan"])
PY
)"

echo "run plan: $RUN_PLAN"
"$AW_BIN" --json benchmark run "$RUN_PLAN" --execution-only | tee "$RUN_JSON"
"$AW_BIN" --json benchmark seal "$RUN_PLAN" | tee "$SEAL_JSON"
"$AW_BIN" --json benchmark seal-verify "$RUN_PLAN" | tee "$SEAL_VERIFY_JSON"

"$PYTHON" - "$SEAL_VERIFY_JSON" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("valid") is not True:
    raise SystemExit("BM6 execution seal verification failed")
print(f"BM6 execution seal verified: {value.get('seal_sha256')}")
PY

SEAL_PATH="$("$PYTHON" - "$SEAL_VERIFY_JSON" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["seal"])
PY
)"

cat <<EOF

BM6 blind execution complete and sealed
  root:       $ROOT
  suite:      $SUITE
  fixture:    $FIXTURE
  run plan:   $RUN_PLAN
  seal:       $SEAL_PATH
  seal check: $SEAL_VERIFY_JSON

No scoring or visual evaluator has been run.
Later scoring may be supplied with:
  agent-workflow benchmark score "$RUN_PLAN" --scoring-bundle /path/to/scoring-bundle
EOF
