#!/usr/bin/env bash
set -euo pipefail

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
AGENT_CLASS="${AGENT_CLASS:-implementation}"
REPETITIONS="${BM3_REPETITIONS:-1}"
ROOT_ARG=""
EVIDENCE_ARG=""

usage() {
  cat <<'USAGE'
Usage: scripts/run-bm3-structured.sh [options]

Run the BM3 development study:
  structured-direct/v1 vs agent-workflow-full/v1

Options:
  --root PATH          durable BM3 artifact root (default: BM3_ROOT or mktemp)
  --repetitions N      paired repetitions (default: BM3_REPETITIONS or 1)
  --agent-class NAME   Agent-Workflow candidate class (default: AGENT_CLASS or implementation)
  --evidence PATH      output evidence archive (default: <root>-evidence.tar.gz)
  -h, --help

Prerequisites:
  Agent-Workflow 0.11.6
  agent-workflow-benchmark 0.3.0
  typesafe-sdk 0.6.0
  comparative decision mode
  TYPESAFE_API_KEY
  authenticated Codex subscription session

The script exports the structured suite, creates the fixture, verifies readiness,
runs paired execution, performs machine scoring, writes a descriptive report,
summarizes granular timing/TypeSafe audit evidence, and creates a self-contained
evidence archive. Development results do not establish a generalized winner.
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
    --evidence)
      shift; [[ $# -gt 0 ]] || { echo "--evidence requires a value" >&2; exit 2; }
      EVIDENCE_ARG="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ ! "$REPETITIONS" =~ ^[1-9][0-9]*$ ]]; then
  echo "BM3_REPETITIONS must be a positive integer; observed: $REPETITIONS" >&2
  exit 2
fi

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
  echo "run Agent-Workflow scripts/build-install-all.sh first" >&2
  exit 1
}
[[ -n "${TYPESAFE_API_KEY:-}" ]] || {
  echo "BM3 requires TYPESAFE_API_KEY because the benchmark runtime uses comparative mode" >&2
  exit 1
}

"$PYTHON" - <<'PY'
from importlib import metadata
from agent_workflow.config import load_settings
from agent_workflow.decisions import require_decision_runtime_ready

required = {
    "agent-workflow": "0.11.6",
    "agent-workflow-benchmark": "0.3.0",
    "typesafe-sdk": "0.6.0",
}
for name, expected in required.items():
    observed = metadata.version(name)
    if observed != expected:
        raise SystemExit(f"{name}={observed}; BM3 requires {expected}")
settings = load_settings()
if settings.decision_mode != "comparative":
    raise SystemExit(
        f"BM3 requires decision_policy.mode='comparative'; observed {settings.decision_mode!r}"
    )
status = require_decision_runtime_ready(settings)
if status.get("ready") is not True:
    raise SystemExit(f"semantic runtime is not ready: {status}")
print(
    "BM3 semantic preflight: "
    f"mode={status['mode']}; typesafe_api_key=configured; comparative_eval=compatible"
)
PY

ROOT="${ROOT_ARG:-${BM3_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-bm3.XXXXXX")}}"
SUITE="$ROOT/suite"
FIXTURE="$ROOT/fixture"
READINESS_JSON="$ROOT/readiness.json"
PLAN_JSON="$ROOT/plan.json"
RUN_JSON="$ROOT/run.json"
SCORE_JSON="$ROOT/score.json"
REPORT_JSON="$ROOT/report-command.json"
SUMMARY_JSON="$ROOT/bm3-summary.json"
EVIDENCE_ARCHIVE="${EVIDENCE_ARG:-${BM3_EVIDENCE_ARCHIVE:-${ROOT}-evidence.tar.gz}}"

mkdir -p "$ROOT"
export AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG="$ROOT/typesafe-api-audit.jsonl"
: > "$AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"
chmod 600 "$AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"

echo "BM3 root: $ROOT"
echo "comparison: structured-direct/v1 vs agent-workflow-full/v1"
echo "repetitions: $REPETITIONS"
echo "shared venv: $DEV_VENV"
echo "TypeSafe audit: $AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"

"$AW_BIN" benchmark structured-value-smoke-export "$SUITE" --agent-class "$AGENT_CLASS"
"$AW_BIN" benchmark fixture-create "$SUITE/benchmark-spec.json" "$FIXTURE"

EXECUTOR="$SUITE/executors/codex-subscription.json"
POLICY="$SUITE/policies/development.json"

"$AW_BIN" --json benchmark readiness "$SUITE/benchmark-spec.json" \
  --executor "$EXECUTOR" \
  --policy "$POLICY" \
  --execution-only > "$READINESS_JSON"

"$PYTHON" - "$READINESS_JSON" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("ready") is not True:
    for check in value.get("checks", []):
        if not check.get("passed"):
            print(f"{check.get('id')}: {check.get('detail')}", file=sys.stderr)
    raise SystemExit("BM3 readiness failed")
print("BM3 readiness: passed")
PY

"$AW_BIN" --json benchmark plan "$SUITE/benchmark-spec.json" \
  --repo "$FIXTURE" \
  --base-ref HEAD \
  --executor "$EXECUTOR" \
  --policy "$POLICY" \
  --repetitions "$REPETITIONS" > "$PLAN_JSON"

RUN_PLAN="$("$PYTHON" - "$PLAN_JSON" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_plan"])
PY
)"

echo "run plan: $RUN_PLAN"
"$AW_BIN" --json benchmark run "$RUN_PLAN" --execution-only | tee "$RUN_JSON"

# Score immediately after paired execution. Missing visual/human evidence may
# keep the run ineligible for a winner, but observed machine scores are still
# valuable for the development comparison.
"$AW_BIN" --json benchmark score "$RUN_PLAN" | tee "$SCORE_JSON"
"$AW_BIN" --json benchmark report "$RUN_PLAN" | tee "$REPORT_JSON"

"$PYTHON" - "$RUN_PLAN" "$ROOT" "$SUMMARY_JSON" <<'PY'
from __future__ import annotations
import json, sys
from pathlib import Path

plan_path = Path(sys.argv[1])
root = Path(sys.argv[2])
out = Path(sys.argv[3])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
run_dir = Path(plan["coordinator"]["run_dir"])

summary = {
    "schema": "agent-workflow/bm3-development-summary/v1",
    "run_id": plan["run_id"],
    "benchmark_id": plan["benchmark_id"],
    "claim_level": plan["claim_level"],
    "treatments": plan.get("treatments"),
    "pairs": [],
    "typesafe": {
        "audit_path": str(root / "typesafe-api-audit.jsonl"),
        "records": 0,
        "duration_ms_total": 0.0,
    },
}

audit = root / "typesafe-api-audit.jsonl"
if audit.is_file():
    for line in audit.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        value = json.loads(line)
        summary["typesafe"]["records"] += 1
        duration = value.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            summary["typesafe"]["duration_ms_total"] += float(duration)
summary["typesafe"]["duration_ms_total"] = round(
    summary["typesafe"]["duration_ms_total"], 3
)

for pair in plan.get("pairs", []):
    state_path = (
        run_dir / "pair-state" / str(pair["case_id"])
        / f"r{int(pair['repetition']):02d}" / "pair.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    attempt_no = int(state["selected_attempt"])
    attempt = next(x for x in pair["attempts"] if int(x["attempt"]) == attempt_no)
    item = {
        "pair_id": pair["pair_id"],
        "repetition": pair["repetition"],
        "selected_attempt": attempt_no,
        "pair_start_skew_seconds": state.get("pair_start_skew_seconds"),
        "arms": {},
    }
    for arm_name, arm in attempt["arms"].items():
        stage_dir = Path(arm["stage_dir"])
        arm_value = json.loads((stage_dir / "arm.json").read_text(encoding="utf-8"))
        score_path = stage_dir / "score.json"
        score_value = (
            json.loads(score_path.read_text(encoding="utf-8"))
            if score_path.is_file()
            else {}
        )
        phases = arm_value.get("phases", [])
        phase_wall = sum(
            float(phase.get("phase_wall_seconds", 0.0))
            for phase in phases
            if isinstance(phase.get("phase_wall_seconds"), (int, float))
            and not isinstance(phase.get("phase_wall_seconds"), bool)
        )
        active = sum(
            float(phase.get("active_process_seconds", 0.0))
            for phase in phases
            if isinstance(phase.get("active_process_seconds"), (int, float))
            and not isinstance(phase.get("active_process_seconds"), bool)
        )
        host_overhead = sum(
            float((phase.get("timing_breakdown") or {}).get("host_overhead_seconds", 0.0))
            for phase in phases
            if isinstance((phase.get("timing_breakdown") or {}).get("host_overhead_seconds"), (int, float))
            and not isinstance((phase.get("timing_breakdown") or {}).get("host_overhead_seconds"), bool)
        )
        item["arms"][arm_name] = {
            "treatment_id": plan["treatments"][arm_name]["treatment_id"],
            "state": arm_value.get("state"),
            "machine_score": score_value.get("machine_score"),
            "machine_score_eligibility": (score_value.get("eligibility") or {}).get("state"),
            "usage": arm_value.get("usage"),
            "timing_totals": {
                "phase_wall_seconds": round(phase_wall, 6),
                "executor_active_seconds": round(active, 6),
                "host_overhead_seconds": round(host_overhead, 6),
            },
            "phase_timings": [
                {
                    "phase_id": phase.get("phase_id"),
                    "phase_wall_seconds": phase.get("phase_wall_seconds"),
                    "active_process_seconds": phase.get("active_process_seconds"),
                    "timing_breakdown": phase.get("timing_breakdown"),
                }
                for phase in phases
            ],
        }
    control = item["arms"].get("control_raw", {})
    candidate = item["arms"].get("workflow_full", {})
    deltas = {}
    for field in ("machine_score",):
        left, right = control.get(field), candidate.get(field)
        deltas[field] = (
            round(float(right) - float(left), 6)
            if isinstance(left, (int, float)) and not isinstance(left, bool)
            and isinstance(right, (int, float)) and not isinstance(right, bool)
            else None
        )
    for field in ("phase_wall_seconds", "executor_active_seconds", "host_overhead_seconds"):
        left = (control.get("timing_totals") or {}).get(field)
        right = (candidate.get("timing_totals") or {}).get(field)
        deltas[field] = (
            round(float(right) - float(left), 6)
            if isinstance(left, (int, float)) and not isinstance(left, bool)
            and isinstance(right, (int, float)) and not isinstance(right, bool)
            else None
        )
    left_tokens = (control.get("usage") or {}).get("provider_total_tokens")
    right_tokens = (candidate.get("usage") or {}).get("provider_total_tokens")
    deltas["provider_total_tokens"] = (
        float(right_tokens) - float(left_tokens)
        if isinstance(left_tokens, (int, float)) and not isinstance(left_tokens, bool)
        and isinstance(right_tokens, (int, float)) and not isinstance(right_tokens, bool)
        else None
    )
    item["deltas"] = deltas
    summary["pairs"].append(item)

out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(f"BM3 summary: {out}")
print(
    "TypeSafe audit: "
    f"{summary['typesafe']['records']} calls; "
    f"{summary['typesafe']['duration_ms_total']} ms total"
)
PY

"$PYTHON" scripts/collect-value-smoke-evidence.py "$ROOT" --output "$EVIDENCE_ARCHIVE"

echo
echo "BM3 development run complete"
echo "  root:     $ROOT"
echo "  summary:  $SUMMARY_JSON"
echo "  score:    $SCORE_JSON"
echo "  report:   $REPORT_JSON"
echo "  audit:    $AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"
echo "  evidence: $EVIDENCE_ARCHIVE"
echo
echo "Do not treat a development run as a generalized treatment-effect claim."
