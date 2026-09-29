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

COMP_REPO="${COMP_REPO:-}"
if [[ -z "$COMP_REPO" && -d "$STACK_ROOT/agent-workflow-comparative-eval" ]]; then
  COMP_REPO="$(cd "$STACK_ROOT/agent-workflow-comparative-eval" && pwd)"
fi

[[ -n "$AW" && -x "$AW" ]] || { echo "error: Agent-Workflow launcher not found" >&2; exit 1; }
[[ -n "$PYTHON" && -x "$PYTHON" ]] || { echo "error: Python not found" >&2; exit 1; }
[[ -n "$COMP_REPO" && -d "$COMP_REPO" ]] || {
  echo "error: comparative-eval checkout not found; set COMP_REPO" >&2
  exit 1
}

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
QUAL_ROOT="${V2_QUALIFICATION_ROOT:-$DATA_HOME/agent-workflow/routing-semantic-v2-qualification}"
ORACLE_ROOT="${V2_ORACLE_ROOT:-$DATA_HOME/agent-workflow/routing-semantic-v2-oracle}"
ORACLE_RUN="${V2_ORACLE_RUN:-$ORACLE_ROOT/run-01}"

MODULE="${V2_MODULE:-$BENCH_REPO/modules/abc-adjudication/routing-semantic-v2.inspect.module.json}"
RUNTIME_LOCK="${V2_RUNTIME_LOCK:-$QUAL_ROOT/runtime-lock.json}"
QUALIFICATION="${V2_QUALIFICATION:-$QUAL_ROOT/qualification.json}"

ORACLE_VIEW="${V2_ORACLE_VIEW:-$COMP_REPO/docs/studies/artifacts/routing-semantic-v2/oracle-authoring-view.json}"
ORACLE_PROTOCOL="${V2_ORACLE_PROTOCOL:-$COMP_REPO/docs/studies/routing-semantic-v2-oracle-protocol.md}"
CORPUS="${V2_CORPUS:-$COMP_REPO/src/agent_workflow_comparative_eval/resources/studies/routing-semantic-v2.corpus.json}"
REVIEW_GUIDE="${V2_REVIEW_GUIDE:-$COMP_REPO/docs/plans/routing-semantic-v2-adjudication-evidence-contract.md}"

A_PASS="$ORACLE_RUN/a/output/adjudication.json"
B_PASS="$ORACLE_RUN/b/output/adjudication.json"
C_PASS="$ORACLE_RUN/c/output/adjudication.json"
DISPUTE_VIEW="$ORACLE_RUN/oracle-disputes-for-c.json"
RESOLUTIONS="$ORACLE_RUN/resolutions.json"
RESOLUTION_REVIEW="$ORACLE_RUN/resolution-review.json"
RESOLUTION_REVIEW_MD="$ORACLE_RUN/resolution-review.md"
ORACLE="$ORACLE_RUN/oracle.json"
LOG_DIR="$ORACLE_ROOT/logs/$(basename "$ORACLE_RUN")"
DIAG_DIR="$ORACLE_ROOT/diagnostics/$(basename "$ORACLE_RUN")"
INGRESS_PROXY="$SCRIPT_DIR/v2-codex-lb-ingress-capture.py"

STUDY="routing-semantic-v2"
MODEL="openai-api/codex-lb/deepseek-flash"

export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

die() {
  echo "error: $*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || die "required file not found: $1"
}

require_clean_new_run() {
  if [[ -e "$ORACLE_RUN" ]]; then
    if [[ ! -d "$ORACLE_RUN" ]]; then
      die "V2_ORACLE_RUN exists and is not a directory: $ORACLE_RUN"
    fi
    if find "$ORACLE_RUN" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      die "V2_ORACLE_RUN already contains evidence; choose a new V2_ORACLE_RUN: $ORACLE_RUN"
    fi
  fi
}

archive_existing_log() {
  local log="$1"
  [[ -e "$log" ]] || return 0
  local archive_dir stamp
  archive_dir="$(dirname "$log")/archive"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$archive_dir"
  mv "$log" "$archive_dir/$(basename "$log" .log)-$stamp.log"
}

run_private() {
  local stage="$1"
  shift
  mkdir -p "$LOG_DIR"
  chmod 700 "$ORACLE_ROOT" "$LOG_DIR" 2>/dev/null || true
  local log="$LOG_DIR/$stage.log"
  archive_existing_log "$log"

  set +e
  "$@" >"$log" 2>&1
  local status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    echo "$stage: FAIL"
    echo "private log: $log"
    exit "$status"
  fi

  echo "$stage: PASS"
  echo "private log: $log"
}

summarize_ingress_capture() {
  local capture="$1"
  local schema_path="$2"
  require_file "$capture"
  require_file "$schema_path"

  "$PYTHON" - "$capture" "$schema_path" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

capture_path, schema_path = map(Path, sys.argv[1:3])

schema = json.loads(schema_path.read_text(encoding="utf-8"))
schema_payload = json.dumps(
    schema,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
expected_sha = hashlib.sha256(schema_payload).hexdigest()

records = []
for line_no, raw in enumerate(capture_path.read_text(encoding="utf-8").splitlines(), start=1):
    if not raw.strip():
        continue
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit(f"capture line {line_no} is not an object")
    if value.get("method") != "POST" or value.get("path") != "/v1/responses":
        continue
    if value.get("model") != "deepseek-flash":
        continue
    records.append((line_no, value))

if not records:
    raise SystemExit("no DeepSeek /v1/responses requests were captured")

failures = []
for line_no, value in records:
    fmt = value.get("text_format")
    if not isinstance(fmt, dict):
        failures.append(f"line {line_no}: missing text_format")
        continue
    if fmt.get("type") != "json_schema":
        failures.append(f"line {line_no}: type={fmt.get('type')!r}")
    if fmt.get("strict") is not True:
        failures.append(f"line {line_no}: strict={fmt.get('strict')!r}")
    if fmt.get("schema_sha256") != expected_sha:
        failures.append(
            f"line {line_no}: schema_sha256={fmt.get('schema_sha256')!r}, expected={expected_sha}"
        )

print(f"structured_requests: {len(records)}")
print(f"schema_sha256: {expected_sha}")
print(f"json_schema_strict: {'pass' if not failures else 'fail'}")
if failures:
    for failure in failures:
        print(f"  {failure}")
    raise SystemExit("sanitized ingress capture did not match the frozen stage schema")
PY
}

run_model_private() {
  local stage="$1"
  local schema_path="$2"
  shift 2

  mkdir -p "$LOG_DIR" "$DIAG_DIR"
  chmod 700 "$ORACLE_ROOT" "$LOG_DIR" "$DIAG_DIR" 2>/dev/null || true

  local log="$LOG_DIR/$stage.log"
  local capture="$DIAG_DIR/$stage-codex-lb-ingress.jsonl"
  local proxy_log="$DIAG_DIR/$stage-codex-lb-ingress-proxy.log"

  [[ ! -e "$log" ]] || die "model-stage log already exists; do not retry this real cohort in place: $log"
  [[ ! -e "$capture" ]] || die "model-stage capture already exists; do not retry this real cohort in place: $capture"
  [[ ! -e "$proxy_log" ]] || die "model-stage proxy log already exists; do not retry this real cohort in place: $proxy_log"

  if [[ "${V2_CAPTURE_CODEX_LB_INGRESS:-1}" != "1" ]]; then
    set +e
    "$@" >"$log" 2>&1
    local direct_status=$?
    set -e
    if [[ "$direct_status" -ne 0 ]]; then
      echo "$stage: FAIL"
      echo "private log: $log"
      exit "$direct_status"
    fi
    echo "$stage: PASS"
    echo "private log: $log"
    return
  fi

  [[ "$CODEX_LB_BASE_URL" == "http://127.0.0.1:2455/v1" ]] ||     die "sanitized ingress capture requires CODEX_LB_BASE_URL=http://127.0.0.1:2455/v1"

  local capture_port="${V2_CODEX_LB_CAPTURE_PORT:-2456}"
  "$PYTHON" "$INGRESS_PROXY"     --listen-host 127.0.0.1     --listen-port "$capture_port"     --upstream http://127.0.0.1:2455     --output "$capture"     >"$proxy_log" 2>&1 &
  local proxy_pid=$!

  "$PYTHON" - "$capture_port" "$proxy_pid" <<'PY'
import os
import socket
import sys
import time

port = int(sys.argv[1])
pid = int(sys.argv[2])
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        raise SystemExit(f"ingress capture proxy exited before readiness: {exc}")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit("timed out waiting for ingress capture proxy")
PY

  set +e
  CODEX_LB_BASE_URL="http://127.0.0.1:$capture_port/v1" "$@" >"$log" 2>&1
  local status=$?
  set -e

  kill "$proxy_pid" 2>/dev/null || true
  wait "$proxy_pid" 2>/dev/null || true

  local capture_status=0
  if [[ -f "$schema_path" && -f "$capture" ]]; then
    set +e
    summarize_ingress_capture "$capture" "$schema_path"
    capture_status=$?
    set -e
  else
    capture_status=1
    echo "structured_requests: unavailable"
    echo "json_schema_strict: fail"
  fi

  if [[ "$status" -ne 0 || "$capture_status" -ne 0 ]]; then
    echo "$stage: FAIL"
    echo "private log: $log"
    echo "sanitized ingress: $capture"
    exit "$([[ "$status" -ne 0 ]] && echo "$status" || echo "$capture_status")"
  fi

  echo "$stage: PASS"
  echo "private log: $log"
  echo "sanitized ingress: $capture"
}

verify_packages() {
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
}

verify_qualification() {
  require_file "$MODULE"
  require_file "$RUNTIME_LOCK"
  require_file "$QUALIFICATION"

  "$PYTHON" - "$MODULE" "$RUNTIME_LOCK" "$QUALIFICATION" "$MODEL" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from agent_workflow_benchmark.benchmarking.adjudication_module import (
    validate_abc_adjudication_module,
)
from agent_workflow_benchmark.benchmarking.inspect_adjudication import _load_runtime_lock
from agent_workflow_benchmark.benchmarking.schema_contracts import validate_instance

module_path, runtime_lock_path, qualification_path = map(Path, sys.argv[1:4])
expected_model = sys.argv[4]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

module = validate_abc_adjudication_module(module_path)
if module.get("study_id") != "routing-semantic-v2":
    raise SystemExit(f"module study mismatch: {module.get('study_id')!r}")

_load_runtime_lock(runtime_lock_path, module)

value = json.loads(qualification_path.read_text(encoding="utf-8"))
validate_instance(
    value,
    "agent-workflow-benchmark/inspect-adjudication-qualification/v2",
    artifact=str(qualification_path),
)
if value.get("qualified") is not True:
    raise SystemExit("qualification does not report qualified=true")

required = [f"IA-{n}" for n in range(1, 12)]
gates = value.get("gates") or {}
failed = [
    gate for gate in required
    if (gates.get(gate) or {}).get("status") != "pass"
]
if failed:
    raise SystemExit(f"non-passing qualification gates: {failed}")

if value.get("module_sha256") != module["module_sha256"]:
    raise SystemExit("qualification module hash does not match current v2 module")
if value.get("runtime_lock_sha256") != sha256(runtime_lock_path):
    raise SystemExit("qualification runtime-lock hash does not match current runtime lock")

model = (
    gates.get("IA-2", {})
    .get("evidence", {})
    .get("model")
)
if model != expected_model:
    raise SystemExit(
        f"qualification model mismatch: observed={model!r}, expected={expected_model!r}"
    )

print("qualification: PASS")
print("qualified: true")
print("gates: IA-1..IA-11 pass")
print(f"model: {model}")
print(f"module_sha256: {module['module_sha256']}")
print(f"runtime_lock_sha256: {sha256(runtime_lock_path)}")
print(f"qualification_sha256: {sha256(qualification_path)}")
PY
}

verify_frozen_inputs() {
  require_file "$MODULE"
  require_file "$ORACLE_VIEW"
  require_file "$ORACLE_PROTOCOL"
  require_file "$CORPUS"

  "$PYTHON" - "$MODULE" "$ORACLE_VIEW" "$ORACLE_PROTOCOL" "$CORPUS" <<'PY'
import hashlib
import sys
from pathlib import Path

from agent_workflow_benchmark.benchmarking.adjudication_module import (
    validate_abc_adjudication_module,
)

module_path, view_path, protocol_path, corpus_path = map(Path, sys.argv[1:5])

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

module = validate_abc_adjudication_module(module_path)
if module.get("study_id") != "routing-semantic-v2":
    raise SystemExit("not a routing-semantic-v2 module")

required = {
    str(item["id"]): item
    for item in module.get("required_files", [])
}
observed = {
    "oracle-view": view_path,
    "oracle-protocol": protocol_path,
    "routing-corpus": corpus_path,
}
for item_id, path in observed.items():
    spec = required.get(item_id)
    if spec is None:
        raise SystemExit(f"module does not pin required file {item_id}")
    got = sha256(path)
    wanted = str(spec.get("sha256") or "")
    if got != wanted:
        raise SystemExit(
            f"{item_id} hash mismatch: observed={got}, expected={wanted}, path={path}"
        )
    print(f"{item_id}: {got}")

task = module.get("task") or {}
if task.get("dataset_version") != "routing-semantic-corpus-v2.0.0":
    raise SystemExit(f"unexpected dataset version: {task.get('dataset_version')!r}")
if task.get("protocol_version") != "routing-semantic-oracle-v2.0.0":
    raise SystemExit(f"unexpected protocol version: {task.get('protocol_version')!r}")

print("frozen inputs: PASS")
PY
}

verify_ready() {
  verify_packages
  verify_qualification
  verify_frozen_inputs
}

validate_pass() {
  local view="$1"
  local adjudication="$2"
  require_file "$view"
  require_file "$adjudication"
  run_private "validate-$(basename "$(dirname "$(dirname "$adjudication")")")"     "$AW" benchmark decision-study-adjudication-validate       "$view" "$adjudication" --study "$STUDY"
}

requires_c() {
  require_file "$DISPUTE_VIEW"
  "$PYTHON" - "$DISPUTE_VIEW" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
cases = value.get("cases")
if not isinstance(cases, list):
    raise SystemExit("dispute view has no valid cases array")
print("true" if cases else "false")
PY
}

dispute_counts() {
  require_file "$DISPUTE_VIEW"
  "$PYTHON" - "$DISPUTE_VIEW" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
cases = value.get("cases") or []
seams = sum(len(item.get("disputed_decision_ids") or []) for item in cases)
print(len(cases), seams)
PY
}

prepare_resolutions() {
  require_file "$A_PASS"
  require_file "$B_PASS"
  require_file "$C_PASS"
  require_file "$DISPUTE_VIEW"

  if [[ -e "$RESOLUTIONS" || -e "$RESOLUTION_REVIEW" || -e "$RESOLUTION_REVIEW_MD" ]]; then
    die "resolution artifacts already exist; preserve/edit them rather than regenerating"
  fi

  BENCH_REPO="$BENCH_REPO" COMP_REPO="$COMP_REPO" AW="$AW" PYTHON="$PYTHON" PRIVATE_ROOT="$ORACLE_ROOT" MODULE="$MODULE" RUNTIME_LOCK="$RUNTIME_LOCK" QUALIFICATION="$QUALIFICATION" ORACLE_VIEW="$ORACLE_VIEW" ORACLE_PROTOCOL="$ORACLE_PROTOCOL" ORACLE_REVIEW_GUIDE="$REVIEW_GUIDE" CORPUS="$CORPUS" ORACLE_RUN="$ORACLE_RUN" DISPUTE_VIEW="$DISPUTE_VIEW" RESOLUTIONS="$RESOLUTIONS" RESOLUTION_REVIEW="$RESOLUTION_REVIEW" RESOLUTION_REVIEW_MD="$RESOLUTION_REVIEW_MD" FREEZE_RERUN_COMMAND="bash scripts/adjudication/v2-oracle.sh freeze" bash "$SCRIPT_DIR/p0b-prepare-resolutions.sh"

  local counts
  counts="$("$PYTHON" - "$RESOLUTIONS" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
records = value.get("records") or []
todo = sum(str(item.get("rationale") or "").startswith("TODO:") for item in records)
unresolved = sum(item.get("status") == "unresolved" for item in records)
print(len(records), todo, unresolved)
PY
)"
  echo "resolution_records: $counts"
}

freeze_oracle() {
  require_file "$A_PASS"
  require_file "$B_PASS"
  require_file "$DISPUTE_VIEW"
  [[ ! -e "$ORACLE" ]] || die "oracle already exists: $ORACLE"

  local args=(
    "$AW" benchmark decision-study-oracle-freeze
    "$ORACLE_VIEW"
    "$A_PASS"
    "$B_PASS"
    "$ORACLE"
    --oracle-version routing-semantic-oracle-v2.0.0
    --study "$STUDY"
  )

  if [[ "$(requires_c)" == "true" ]]; then
    require_file "$C_PASS"
    args+=(--c-view "$DISPUTE_VIEW" --c-pass "$C_PASS")

    if [[ ! -f "$RESOLUTIONS" ]]; then
      prepare_resolutions
    fi

    local resolution_count unresolved_count todo_count
    read -r resolution_count unresolved_count todo_count < <(
      "$PYTHON" - "$RESOLUTIONS" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
records = value.get("records") or []
unresolved = sum(item.get("status") == "unresolved" for item in records)
todo = sum(
    str(item.get("rationale") or "").strip().startswith("TODO:")
    for item in records
)
print(len(records), unresolved, todo)
PY
    )

    if [[ "$todo_count" -gt 0 ]]; then
      echo "freeze: BLOCKED"
      echo "reason: $todo_count resolution record(s) still contain TODO rationale text"
      echo "review: $RESOLUTION_REVIEW_MD"
      echo "edit: $RESOLUTIONS"
      exit 3
    fi
    if [[ "$unresolved_count" -gt 0 && "${ALLOW_UNRESOLVED_RESOLUTIONS:-0}" != "1" ]]; then
      echo "freeze: BLOCKED"
      echo "reason: $unresolved_count three-way conflict(s) remain unresolved"
      echo "set ALLOW_UNRESOLVED_RESOLUTIONS=1 only if preserving unresolved conflicts is intentional"
      exit 3
    fi
    if [[ "$resolution_count" -gt 0 ]]; then
      args+=(--resolutions "$RESOLUTIONS")
    fi
  fi

  run_private "freeze" "${args[@]}"
}

validate_oracle() {
  require_file "$ORACLE"
  run_private "validate-oracle"     "$AW" benchmark decision-study-validate       "$CORPUS" --oracle "$ORACLE" --study "$STUDY"
}

status() {
  echo "study: $STUDY"
  echo "module: $MODULE"
  echo "qualification: $QUALIFICATION"
  echo "runtime_lock: $RUNTIME_LOCK"
  echo "oracle_run: $ORACLE_RUN"
  echo "A: $([[ -f "$A_PASS" ]] && echo present || echo absent)"
  echo "B: $([[ -f "$B_PASS" ]] && echo present || echo absent)"
  echo "disputes: $([[ -f "$DISPUTE_VIEW" ]] && echo present || echo absent)"
  echo "C: $([[ -f "$C_PASS" ]] && echo present || echo absent)"
  echo "resolutions: $([[ -f "$RESOLUTIONS" ]] && echo present || echo absent)"
  echo "oracle: $([[ -f "$ORACLE" ]] && echo present || echo absent)"
  echo "oracle_manifest: $([[ -f "$ORACLE.manifest.json" ]] && echo present || echo absent)"
}

run_ab() {
  verify_ready
  require_clean_new_run
  mkdir -p "$ORACLE_RUN"
  chmod 700 "$ORACLE_RUN"

  run_model_private "run-ab" "$ORACLE_RUN/inspect-logs/primary/codex-output-schema.json" "$AW" benchmark adjudication-inspect-run-primary "$MODULE" "$ORACLE_VIEW" "$ORACLE_PROTOCOL" "$RUNTIME_LOCK" "$QUALIFICATION" "$ORACLE_RUN" --model "$MODEL" --model-arg responses_api=true

  validate_pass "$ORACLE_VIEW" "$A_PASS"
  validate_pass "$ORACLE_VIEW" "$B_PASS"
  echo "A/B: PASS"
}

compute_disputes() {
  verify_ready
  require_file "$A_PASS"
  require_file "$B_PASS"
  [[ ! -e "$DISPUTE_VIEW" ]] || die "dispute view already exists: $DISPUTE_VIEW"

  run_private "compute-disputes"     "$AW" benchmark decision-study-oracle-disputes       "$ORACLE_VIEW" "$A_PASS" "$B_PASS" "$DISPUTE_VIEW"       --study "$STUDY"

  local cases seams
  read -r cases seams < <(dispute_counts)
  echo "disputed_cases: $cases"
  echo "disputed_seams: $seams"
  echo "requires_c: $(requires_c)"
}

run_c() {
  verify_ready
  require_file "$DISPUTE_VIEW"

  if [[ "$(requires_c)" != "true" ]]; then
    echo "C: not required"
    return
  fi
  [[ ! -e "$C_PASS" ]] || die "C adjudication already exists: $C_PASS"

  run_model_private "run-c" "$ORACLE_RUN/inspect-logs/tiebreaker/codex-output-schema.json" "$AW" benchmark adjudication-inspect-run-c "$MODULE" "$DISPUTE_VIEW" "$ORACLE_PROTOCOL" "$RUNTIME_LOCK" "$QUALIFICATION" "$ORACLE_RUN" --model "$MODEL" --model-arg responses_api=true

  validate_pass "$DISPUTE_VIEW" "$C_PASS"
  echo "C: PASS"
}

run_all() {
  run_ab
  compute_disputes
  run_c

  if [[ "$(requires_c)" == "true" ]]; then
    prepare_resolutions
    local pending
    pending="$("$PYTHON" - "$RESOLUTIONS" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
records = value.get("records") or []
print(sum(str(item.get("rationale") or "").strip().startswith("TODO:") for item in records))
PY
)"
    if [[ "$pending" -gt 0 ]]; then
      echo
      echo "real v2 oracle: HUMAN RESOLUTION REQUIRED"
      echo "review: $RESOLUTION_REVIEW_MD"
      echo "edit: $RESOLUTIONS"
      echo "after review: bash scripts/adjudication/v2-oracle.sh freeze"
      exit 3
    fi
  fi

  freeze_oracle
  validate_oracle
  echo "real v2 oracle workflow: COMPLETE"
  echo "oracle: $ORACLE"
}

usage() {
  cat <<'EOF'
usage: scripts/adjudication/v2-oracle.sh COMMAND

Commands:
  verify              Verify package versions, IA-1..IA-11 qualification, and frozen inputs.
  status              Show which private v2 oracle artifacts currently exist.
  run-ab              Run and validate independent real A/B adjudication.
  compute-disputes    Create the blinded C-only dispute view.
  run-c               Run and validate C only when A/B disputes require it.
  prepare-resolutions Build the private human-review artifacts for three-way conflicts.
  freeze              Freeze the v2 oracle; blocks on unresolved/TODO resolutions by default.
  validate-oracle     Validate the frozen v2 oracle against the frozen v2 corpus.
  run-all             Run through the workflow and stop at any required human resolution.

Environment:
  V2_ORACLE_ROOT       Private root (default: ~/.local/share/agent-workflow/routing-semantic-v2-oracle)
  V2_ORACLE_RUN        Private run directory (default: $V2_ORACLE_ROOT/run-01)
  V2_QUALIFICATION_ROOT
                       Existing qualified runtime root from v2-qualify.sh
  COMP_REPO            Comparative-eval checkout when not a sibling repository

The script is intentionally fail-closed. It never retries an existing real run in place.
Choose a new V2_ORACLE_RUN for any deliberate rerun.
EOF
}

command="${1:-}"
case "$command" in
  verify)
    verify_ready
    ;;
  status)
    status
    ;;
  run-ab)
    run_ab
    ;;
  compute-disputes)
    compute_disputes
    ;;
  run-c)
    run_c
    ;;
  prepare-resolutions)
    verify_ready
    prepare_resolutions
    ;;
  freeze)
    verify_ready
    freeze_oracle
    ;;
  validate-oracle)
    verify_ready
    validate_oracle
    ;;
  run-all)
    run_all
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    die "unknown command: $command"
    ;;
esac
