#!/usr/bin/env bash
set -euo pipefail

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
AGENT_CLASS="${AGENT_CLASS:-implementation}"

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
[[ -n "$AW_PATH" ]] || {
  echo "Agent-Workflow launcher not found: $AW_BIN" >&2
  exit 1
}

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

[[ -x "$DEV_VENV/bin/python" || -x "$DEV_VENV/bin/python3" ]] || {
  echo "could not resolve shared Agent-Workflow virtualenv from $AW_PATH" >&2
  exit 1
}
if [[ -x "$DEV_VENV/bin/python" ]]; then PYTHON="$DEV_VENV/bin/python"; else PYTHON="$DEV_VENV/bin/python3"; fi

export VIRTUAL_ENV="$DEV_VENV"
export AGENT_WORKFLOW_VENV="$DEV_VENV"
export AGENT_WORKFLOW_BIN="$DEV_VENV/bin/agent-workflow"
export PATH="$DEV_VENV/bin:$PATH"
export XDG_CONFIG_HOME="$DEV_VENV/.xdg/config"
export XDG_STATE_HOME="$DEV_VENV/.xdg/state"
export XDG_DATA_HOME="$DEV_VENV/.xdg/data"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_DATA_HOME"

AW_BIN="$AGENT_WORKFLOW_BIN"
DEV_CONFIG="$XDG_CONFIG_HOME/agent-workflow/config.toml"
[[ -f "$DEV_CONFIG" ]] || {
  echo "venv-local Agent-Workflow config is missing: $DEV_CONFIG" >&2
  echo "run the Agent-Workflow and benchmark build-install scripts first" >&2
  exit 1
}

[[ -n "${TYPESAFE_API_KEY:-}" ]] || {
  echo "value smoke requires TYPESAFE_API_KEY because benchmark runtime uses comparative mode" >&2
  exit 1
}

"${PYTHON}" - <<'PY'
from agent_workflow.config import load_settings
from agent_workflow.decisions import require_decision_runtime_ready

settings = load_settings()
if settings.decision_mode != "comparative":
    raise SystemExit(
        f"value smoke requires decision_policy.mode='comparative'; observed {settings.decision_mode!r}"
    )
status = require_decision_runtime_ready(settings)
print(
    "semantic preflight: "
    f"mode={status['mode']}; "
    "typesafe_api_key=configured; comparative_eval=compatible"
)
PY

ROOT="${VALUE_SMOKE_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-value-smoke.XXXXXX")}"
SUITE="${ROOT}/suite"
FIXTURE="${ROOT}/fixture"
READINESS_JSON="${ROOT}/readiness.json"
PLAN_JSON="${ROOT}/plan.json"
RUN_JSON="${ROOT}/run.json"

mkdir -p "${ROOT}"
export AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG="${ROOT}/typesafe-api-audit.jsonl"
: > "${AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG}"
chmod 600 "${AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG}"

echo "value-smoke root: ${ROOT}"
echo "shared venv: ${DEV_VENV}"
echo "XDG config: ${XDG_CONFIG_HOME}"
echo "XDG state: ${XDG_STATE_HOME}"
echo "XDG data: ${XDG_DATA_HOME}"
"${AW_BIN}" benchmark value-smoke-export "${SUITE}" --agent-class "${AGENT_CLASS}"
"${AW_BIN}" benchmark fixture-create "${SUITE}/benchmark-spec.json" "${FIXTURE}"

EXECUTOR="${SUITE}/executors/codex-subscription.json"
POLICY="${SUITE}/policies/development.json"

if [[ ! -f "${EXECUTOR}" ]]; then
  echo "executor profile not found: ${EXECUTOR}" >&2
  exit 2
fi

"${AW_BIN}" --json benchmark readiness "${SUITE}/benchmark-spec.json" \
  --executor "${EXECUTOR}" \
  --policy "${POLICY}" \
  --execution-only > "${READINESS_JSON}"

"${PYTHON}" - "${READINESS_JSON}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
if value.get("ready") is not True:
    print("value-smoke readiness failed:", file=sys.stderr)
    for check in value.get("checks", []):
        if not check.get("passed"):
            print(f"  - {check.get('id')}: {check.get('detail')}", file=sys.stderr)
    raise SystemExit(2)
print("readiness: passed")
for check in value.get("checks", []):
    print(f"  - {check.get('id')}: {check.get('detail')}")
PY

"${AW_BIN}" --json benchmark plan "${SUITE}/benchmark-spec.json" \
  --repo "${FIXTURE}" \
  --base-ref HEAD \
  --executor "${EXECUTOR}" \
  --policy "${POLICY}" > "${PLAN_JSON}"

RUN_PLAN="$("${PYTHON}" - "${PLAN_JSON}" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value["run_plan"])
PY
)"

echo "run plan: ${RUN_PLAN}"
"${AW_BIN}" --json benchmark run "${RUN_PLAN}" --execution-only | tee "${RUN_JSON}"

"${PYTHON}" - "${PLAN_JSON}" "${RUN_JSON}" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
print("")
print("value smoke completed")
print(f"  run_id: {plan.get('run_id')}")
print(f"  run_dir: {result.get('run_dir') or plan.get('run_dir')}")
print(f"  report: {result.get('report')}")
print(f"  state: {result.get('state')}")
PY

"${PYTHON}" - "${RUN_PLAN}" "${ROOT}" <<'PY'
import json
import sys
from pathlib import Path

plan_path = Path(sys.argv[1])
smoke_root = Path(sys.argv[2])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
run_dir = Path(plan["coordinator"]["run_dir"])

failures = []
print("")
print("token evidence qualification:")
for pair in plan.get("pairs", []):
    pair_state_path = (
        run_dir
        / "pair-state"
        / str(pair["case_id"])
        / f"r{int(pair['repetition']):02d}"
        / "pair.json"
    )
    if not pair_state_path.is_file():
        failures.append(f"{pair['pair_id']}: missing pair evidence {pair_state_path}")
        continue
    pair_state = json.loads(pair_state_path.read_text(encoding="utf-8"))
    selected_attempt = int(pair_state["selected_attempt"])
    attempt = next(
        (item for item in pair.get("attempts", []) if int(item["attempt"]) == selected_attempt),
        None,
    )
    if attempt is None:
        failures.append(f"{pair['pair_id']}: selected attempt {selected_attempt} absent from run plan")
        continue
    for arm_name, arm in attempt["arms"].items():
        arm_path = Path(arm["stage_dir"]) / "arm.json"
        if not arm_path.is_file():
            failures.append(f"{pair['pair_id']}/{arm_name}: missing {arm_path}")
            continue
        arm_value = json.loads(arm_path.read_text(encoding="utf-8"))
        usage = arm_value.get("usage", {})
        complete = usage.get("token_evidence_complete") is True
        print(
            f"  - {pair['pair_id']}/{arm_name}: complete={complete}; "
            f"input={usage.get('input_tokens')}; cached={usage.get('cached_input_tokens')}; "
            f"output={usage.get('output_tokens')}; reasoning={usage.get('reasoning_output_tokens')}; "
            f"total={usage.get('provider_total_tokens')}"
        )
        if not complete:
            failures.append(f"{pair['pair_id']}/{arm_name}: token_evidence_complete is not true")

if failures:
    print("", file=sys.stderr)
    print("value-smoke execution completed, but token evidence qualification failed:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    print(f"artifacts preserved at: {smoke_root}", file=sys.stderr)
    print(f"collect them with: python scripts/collect-value-smoke-evidence.py {smoke_root}", file=sys.stderr)
    raise SystemExit(3)

print("token evidence qualification: passed")
PY
echo "local smoke artifacts: ${ROOT}"
echo "TypeSafe audit: ${AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG} ($(wc -l < "${AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG}") records)"
echo "smoke XDG isolation was process-local; caller shell environment is unchanged"
echo "collect durable evidence with:"
echo "  python scripts/collect-value-smoke-evidence.py ${ROOT}"
