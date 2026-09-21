#!/usr/bin/env bash
set -euo pipefail

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
AGENT_CLASS="${AGENT_CLASS:-implementation}"
ROOT="${VALUE_SMOKE_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-value-smoke.XXXXXX")}"
SUITE="${ROOT}/suite"
FIXTURE="${ROOT}/fixture"
READINESS_JSON="${ROOT}/readiness.json"
PLAN_JSON="${ROOT}/plan.json"
RUN_JSON="${ROOT}/run.json"

mkdir -p "${ROOT}"

echo "value-smoke root: ${ROOT}"
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

python - "${READINESS_JSON}" <<'PY'
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

RUN_PLAN="$(python - "${PLAN_JSON}" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value["run_plan"])
PY
)"

echo "run plan: ${RUN_PLAN}"
"${AW_BIN}" --json benchmark run "${RUN_PLAN}" --execution-only | tee "${RUN_JSON}"

python - "${PLAN_JSON}" "${RUN_JSON}" <<'PY'
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

echo "local smoke artifacts: ${ROOT}"
