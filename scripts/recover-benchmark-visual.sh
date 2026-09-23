#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  3. temporarily applies a corrected, provenance-recorded visual evaluator when an\n     already-executed development run contains the superseded Priority Picker harness;\n  4. starts/reuses live review apps;\n  5. retries failed visual captures while preserving prior failures;\n  6. prints concrete assessment failure details;\n  7. stops live review apps and restores the frozen evaluator copy.\n
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

# Existing runs freeze their evaluator under the coordinator suite. For the
# Priority Picker v2 visual-harness bug fixed after execution, temporarily use
# the corrected evaluator for evidence collection only, record the substitution,
# and restore the frozen suite before exit. Model execution artifacts are never
# touched.
HARNESS_TARGET=""
HARNESS_BACKUP=""
CURRENT_HARNESS="$REPO_ROOT/src/agent_workflow_benchmark/assets/benchmarks/_shared/priority-picker-v2-fast/evaluation/capture_visual.py"

HARNESS_INFO="$("$PYTHON" - "$PLAN" "$CURRENT_HARNESS" <<'PY'
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
current = Path(sys.argv[2]).resolve()
spec = json.loads(Path(plan["coordinator"]["spec_path"]).read_text(encoding="utf-8"))
benchmark_id = str(plan.get("benchmark_id", ""))
claim_level = str(plan.get("claim_level", ""))
suite = Path(plan["coordinator"]["suite_dir"])

target = None
for item in spec.get("visual", {}).get("capture_argv", []):
    text = str(item)
    prefix = "{suite}/"
    if text.startswith(prefix) and text.endswith(".py"):
        target = (suite / text[len(prefix):]).resolve()
        break

def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

eligible = (
    benchmark_id in {"priority-picker-v2", "priority-picker-fast-v1"}
    and claim_level == "development"
    and target is not None
    and target.is_file()
    and current.is_file()
    and digest(target) != digest(current)
)
print(json.dumps({
    "benchmark_id": benchmark_id,
    "claim_level": claim_level,
    "target": str(target) if target else None,
    "current": str(current),
    "target_sha256": digest(target) if target else None,
    "current_sha256": digest(current),
    "eligible": eligible,
}))
PY
)"

if "$PYTHON" - "$HARNESS_INFO" <<'PY'
import json, sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("eligible") else 1)
PY
then
  HARNESS_TARGET="$("$PYTHON" - "$HARNESS_INFO" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["target"])
PY
)"
  HARNESS_BACKUP="$OUTPUT_ROOT/capture_visual.original.py"
  cp -p "$HARNESS_TARGET" "$HARNESS_BACKUP"
  cp -p "$CURRENT_HARNESS" "$HARNESS_TARGET"
  "$PYTHON" - "$HARNESS_INFO" "$RUN_ID" "$OUTPUT_ROOT/harness-substitution.json" <<'PY'
import json, sys
from pathlib import Path
info = json.loads(sys.argv[1])
value = {
    "schema": "agent-workflow/benchmark-harness-substitution/v1",
    "run_id": sys.argv[2],
    "benchmark_id": info["benchmark_id"],
    "claim_level": info["claim_level"],
    "scope": "visual-capture-only",
    "reason": (
        "Correct the documented Priority Picker visual evaluator defect where "
        "solution/UI failures were escalated to harness failures and the UI "
        "sort check required an undocumented hard-coded title option."
    ),
    "frozen_evaluator": info["target"],
    "frozen_evaluator_sha256": info["target_sha256"],
    "replacement_evaluator": info["current"],
    "replacement_evaluator_sha256": info["current_sha256"],
    "model_execution_modified": False,
}
Path(sys.argv[3]).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
print(
    "temporary visual evaluator correction: "
    f"{info['target_sha256']} -> {info['current_sha256']}"
)
PY
fi

# Preserve and clear only failed visual-capture cache. This is intentionally
# implemented in the recovery script so an already-executed run can be
# recovered with the installed benchmark version that produced it.
"$PYTHON" - "$PLAN" <<'PY'
from __future__ import annotations
import json, shutil, sys
from pathlib import Path

plan_path = Path(sys.argv[1])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
run_dir = Path(plan["coordinator"]["run_dir"])

summary_path = run_dir / "visual-capture-summary.json"
if summary_path.is_file():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if int(summary.get("harness_failures", 0)) > 0:
        history = run_dir / "visual-capture-history"
        history.mkdir(parents=True, exist_ok=True)
        index = 1
        while (history / f"failed-{index:02d}.json").exists():
            index += 1
        shutil.copy2(summary_path, history / f"failed-{index:02d}.json")
        summary_path.unlink()

for pair in plan.get("pairs", []):
    state_path = (
        run_dir / "pair-state" / str(pair["case_id"])
        / f"r{int(pair['repetition']):02d}" / "pair.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    selected = int(state["selected_attempt"])
    attempt = next(
        item for item in pair["attempts"]
        if int(item["attempt"]) == selected
    )
    for arm in attempt["arms"].values():
        visual = Path(arm["stage_dir"]) / "visual"
        capture = visual / "capture.json"
        if not capture.is_file():
            continue
        value = json.loads(capture.read_text(encoding="utf-8"))
        if value.get("state") == "complete":
            continue
        history = visual.parent / "visual-history"
        history.mkdir(parents=True, exist_ok=True)
        index = 1
        while (history / f"failed-{index:02d}").exists():
            index += 1
        destination = history / f"failed-{index:02d}"
        print(f"preserving failed visual capture: {visual} -> {destination}")
        shutil.move(str(visual), str(destination))
PY

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
  if [[ -n "$HARNESS_TARGET" && -n "$HARNESS_BACKUP" && -f "$HARNESS_BACKUP" ]]; then
    cp -p "$HARNESS_BACKUP" "$HARNESS_TARGET"
  fi
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
