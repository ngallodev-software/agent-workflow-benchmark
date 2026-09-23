#!/usr/bin/env bash
set -euo pipefail

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
TARGET=""
OUTPUT_ROOT=""

usage() {
  cat <<'USAGE'
Usage: bash scripts/recover-benchmark-visual.sh RUN_ID_OR_PLAN [--output-root PATH]

Recover/retry only the visual-capture stage of an already executed benchmark.
The script never reruns model execution. It:
  1. resolves run-plan.json;
  2. verifies the run's effective visual runtime lock;
  3. starts/reuses live review apps;
  4. retries failed visual captures (prior failures are preserved by the plugin);
  5. prints concrete assessment failure details;
  6. stops live review apps.

Requires the benchmark plugin version containing retryable visual capture support.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root)
      shift; [[ $# -gt 0 ]] || { echo "--output-root requires a path" >&2; exit 2; }
      OUTPUT_ROOT="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -n "$TARGET" ]]; then
        echo "unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      TARGET="$1"
      ;;
  esac
  shift
done

[[ -n "$TARGET" ]] || { usage >&2; exit 2; }

if [[ "$AW_BIN" == */* ]]; then
  AW_PATH="$AW_BIN"
else
  AW_PATH="$(command -v "$AW_BIN" 2>/dev/null || true)"
fi
[[ -n "$AW_PATH" ]] || { echo "Agent-Workflow launcher not found: $AW_BIN" >&2; exit 1; }
PYTHON="$(dirname "$AW_PATH")/python"
[[ -x "$PYTHON" ]] || PYTHON="$(dirname "$AW_PATH")/python3"
[[ -x "$PYTHON" ]] || { echo "Python not found beside $AW_PATH" >&2; exit 1; }

PLAN="$("$PYTHON" - "$TARGET" <<'PY'
from pathlib import Path
import sys
from agent_workflow.config import load_settings

value = Path(sys.argv[1]).expanduser()
if value.exists():
    if value.is_dir():
        value = value / "run-plan.json"
    plan = value.resolve()
else:
    settings = load_settings()
    run_id = sys.argv[1]
    plan = (
        settings.worktree_root / "benchmarks" / run_id / "coordinator"
        / "benchmarks" / "runs" / run_id / "run-plan.json"
    ).resolve()
if not plan.is_file():
    raise SystemExit(f"benchmark run plan not found: {plan}")
print(plan)
PY
)"

RUN_ID="$("$PYTHON" - "$PLAN" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_id"])
PY
)"

if [[ -z "$OUTPUT_ROOT" ]]; then
  OUTPUT_ROOT="${TMPDIR:-/tmp}/agent-workflow-benchmark-recovery-$RUN_ID"
fi
mkdir -p "$OUTPUT_ROOT"

LOCK="$("$PYTHON" - "$PLAN" <<'PY'
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
suite = Path(plan["coordinator"]["suite_dir"])
spec = json.loads(Path(plan["coordinator"]["spec_path"]).read_text(encoding="utf-8"))
print((suite / spec["visual"]["runtime_lock_path"]).resolve())
PY
)"

echo "run_id: $RUN_ID"
echo "run_plan: $PLAN"
echo "runtime_lock: $LOCK"
echo "output_root: $OUTPUT_ROOT"

"$AW_PATH" --json benchmark runtime-attest "$LOCK" --claim-level development   > "$OUTPUT_ROOT/runtime-attestation.json"

"$PYTHON" - "$OUTPUT_ROOT/runtime-attestation.json" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("runtime_state:", value.get("runtime_state"))
if value.get("runtime_state") not in {"development-verified", "publication-verified"}:
    for key, passed in (value.get("checks") or {}).items():
        if not passed and key != "content_addressed_container":
            print(f"failed runtime check: {key}", file=sys.stderr)
    raise SystemExit("visual runtime is not development-verified")
PY

"$AW_PATH" --json benchmark live-start "$PLAN" > "$OUTPUT_ROOT/live-start.json"
cleanup() {
  "$AW_PATH" --json benchmark live-stop "$PLAN" > "$OUTPUT_ROOT/live-stop.json" 2>/dev/null || true
}
trap cleanup EXIT

"$AW_PATH" --json benchmark visual-capture "$PLAN"   | tee "$OUTPUT_ROOT/visual-capture.json"

"$PYTHON" - "$OUTPUT_ROOT/visual-capture.json" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
failures = [item for item in value.get("captures", []) if item.get("state") != "complete"]
for item in failures:
    print(
        f"visual failure: pair={item.get('pair_id')} arm={item.get('arm')} "
        f"runtime={item.get('runtime_state')}",
        file=sys.stderr,
    )
    details = item.get("failure_details") or []
    if not details and item.get("assessment"):
        path = Path(item["assessment"])
        if path.is_file():
            assessment = json.loads(path.read_text(encoding="utf-8"))
            details = [
                str(check.get("detail"))
                for check in assessment.get("checks", [])
                if check.get("passed") is False
            ]
    for detail in details:
        print(f"  {detail}", file=sys.stderr)
if failures:
    raise SystemExit(f"visual capture failed for {len(failures)} arm(s)")
print(f"visual capture complete: {value.get('complete', 0)} arm(s)")
PY

trap - EXIT
cleanup

echo "visual recovery complete"
