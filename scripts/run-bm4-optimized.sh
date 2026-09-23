#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
AGENT_CLASS="${AGENT_CLASS:-implementation}"
REPETITIONS="${BM4_REPETITIONS:-1}"
ROOT_ARG=""
EVIDENCE_ARG=""
RESULTS_REPO_ARG="${BM4_RESULTS_REPO:-}"

usage() {
  cat <<'USAGE'
Usage: scripts/run-bm4-optimized.sh [options]

Run the BM4 optimization study:
  structured-direct/v1 vs agent-workflow-optimized/v1
  both arms: gpt-6-luna, high reasoning effort

Options:
  --root PATH          durable BM4 artifact root (default: BM4_ROOT or mktemp)
  --repetitions N      paired repetitions (default: BM4_REPETITIONS or 1)
  --agent-class NAME   Agent-Workflow candidate class (default: AGENT_CLASS or implementation)
  --evidence PATH      output evidence archive (default: <root>-evidence.tar.gz)
  --results-repo PATH  sanitized results repo (default: sibling agent-workflow-benchmark-results)
  -h, --help

Prerequisites:
  Agent-Workflow 0.11.6
  agent-workflow-benchmark 0.3.1
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
    --results-repo)
      shift; [[ $# -gt 0 ]] || { echo "--results-repo requires a value" >&2; exit 2; }
      RESULTS_REPO_ARG="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ ! "$REPETITIONS" =~ ^[1-9][0-9]*$ ]]; then
  echo "BM4_REPETITIONS must be a positive integer; observed: $REPETITIONS" >&2
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
  echo "BM4 requires TYPESAFE_API_KEY because the benchmark runtime uses comparative mode" >&2
  exit 1
}

"$PYTHON" - <<'PY'
from importlib import metadata
from agent_workflow.config import load_settings
from agent_workflow.decisions import require_decision_runtime_ready

required = {
    "agent-workflow": "0.11.6",
    "agent-workflow-benchmark": "0.3.1",
    "typesafe-sdk": "0.6.0",
}
for name, expected in required.items():
    observed = metadata.version(name)
    if observed != expected:
        raise SystemExit(f"{name}={observed}; BM4 requires {expected}")
settings = load_settings()
if settings.decision_mode != "comparative":
    raise SystemExit(
        f"BM4 requires decision_policy.mode='comparative'; observed {settings.decision_mode!r}"
    )
status = require_decision_runtime_ready(settings)
if status.get("ready") is not True:
    raise SystemExit(f"semantic runtime is not ready: {status}")
print(
    "BM4 semantic preflight: "
    f"mode={status['mode']}; typesafe_api_key=configured; comparative_eval=compatible"
)
PY

ROOT="${ROOT_ARG:-${BM4_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-bm4.XXXXXX")}}"
SUITE="$ROOT/suite"
FIXTURE="$ROOT/fixture"
READINESS_JSON="$ROOT/readiness.json"
PLAN_JSON="$ROOT/plan.json"
RUN_JSON="$ROOT/run.json"
SCORE_JSON="$ROOT/score.json"
CONSOLIDATE_JSON="$ROOT/consolidate.json"
REPORT_JSON="$ROOT/report-command.json"
SUMMARY_JSON="$ROOT/bm4-summary.json"
SEMANTIC_QUALIFICATION_JSON="$ROOT/typesafe-semantic-qualification.json"
EVIDENCE_ARCHIVE="${EVIDENCE_ARG:-${BM4_EVIDENCE_ARCHIVE:-${ROOT}-evidence.tar.gz}}"

mkdir -p "$ROOT"
export AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG="$ROOT/typesafe-api-audit.jsonl"
: > "$AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"
chmod 600 "$AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"

echo "BM4 root: $ROOT"
echo "comparison: structured-direct/v1 vs agent-workflow-optimized/v1"
echo "repetitions: $REPETITIONS"
echo "shared venv: $DEV_VENV"
echo "TypeSafe audit: $AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"

"$AW_BIN" benchmark bm4-export "$SUITE" --agent-class "$AGENT_CLASS"

"$PYTHON" - "$SUITE" <<'PY'
import json, sys
from pathlib import Path

suite = Path(sys.argv[1])
executor = json.loads((suite / "executors" / "codex-subscription.json").read_text(encoding="utf-8"))
spec = json.loads((suite / "benchmark-spec.json").read_text(encoding="utf-8"))
if executor.get("model") != "gpt-6-luna" or executor.get("effort") != "high":
    raise SystemExit(
        f"BM4 requires gpt-6-luna/high; observed model={executor.get('model')!r} effort={executor.get('effort')!r}"
    )
candidate = spec.get("arms", {}).get("candidate", {})
if candidate.get("treatment_id") != "agent-workflow-optimized/v1":
    raise SystemExit(f"BM4 candidate treatment mismatch: {candidate.get('treatment_id')!r}")
print("BM4 treatment preflight: gpt-6-luna/high; candidate=agent-workflow-optimized/v1")
PY

# Exercise the real Agent-Workflow routing decision boundary outside the paired
# treatment. This produces private TypeSafe v2 request/response evidence without
# changing either benchmark arm or charging semantic-routing time to the candidate.
"$PYTHON" - "$SUITE" "$SEMANTIC_QUALIFICATION_JSON" "$AGENT_CLASS" <<'PY'
from __future__ import annotations
import json, os, sys
from pathlib import Path

from agent_workflow.config import load_settings
from agent_workflow.routing import advise_routing_with_policy

suite = Path(sys.argv[1])
out = Path(sys.argv[2])
agent_class = sys.argv[3]
settings = load_settings()
audit = Path(os.environ["AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"])

def audit_count() -> int:
    if not audit.is_file():
        return 0
    return sum(1 for line in audit.read_text(encoding="utf-8").splitlines() if line)

spec = json.loads((suite / "benchmark-spec.json").read_text(encoding="utf-8"))
before = audit_count()
contexts = []
for phase in spec["phases"]:
    prompt_path = suite / phase["prompt_path"]
    text = prompt_path.read_text(encoding="utf-8").strip()
    metadata = {
        "task_type": "implementation",
        "risk": "normal",
        "requires_interaction": False,
        "benchmark_id": spec["benchmark_id"],
        "phase_id": phase["id"],
        "phase_name": phase["name"],
        "purpose": "pre-benchmark semantic routing qualification only",
    }
    advice = advise_routing_with_policy(
        metadata,
        settings,
        enforced_selection={"agent_class": agent_class},
        task_text=text,
        source_ref=f"bm4:{spec['benchmark_id']}:{phase['id']}",
    )
    contexts.append({
        "phase_id": phase["id"],
        "phase_name": phase["name"],
        "prompt_path": phase["prompt_path"],
        "prompt_text": text,
        "deterministic_control": advice.get("deterministic_control"),
        "counterfactual_candidate": advice.get("counterfactual_candidate"),
        "decision_receipts": advice.get("decision_receipts"),
        "decision_timing": advice.get("decision_timing"),
        "applied": {
            "recommendation": advice.get("recommendation"),
            "enforced_selection": advice.get("enforced_selection"),
        },
    })
after = audit_count()
value = {
    "schema": "agent-workflow/bm4-typesafe-semantic-qualification/v1",
    "benchmark_id": spec["benchmark_id"],
    "decision_mode": settings.decision_mode,
    "decision_profile": settings.decision_profile,
    "treatment_includes_semantic_routing": False,
    "purpose": (
        "Exercise the real routing Choice/Noul/Score boundary on representative BM4 "
        "phase context before paired execution; this is diagnostic evidence, not a treatment."
    ),
    "audit_path": str(audit),
    "audit_records_before": before,
    "audit_records_after": after,
    "qualification_calls": after - before,
    "contexts": contexts,
}
out.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
if value["qualification_calls"] != len(contexts):
    raise SystemExit(
        f"expected {len(contexts)} TypeSafe qualification calls; observed {value['qualification_calls']}"
    )
print(
    f"TypeSafe semantic qualification: {len(contexts)} contexts; "
    f"{value['qualification_calls']} audited calls"
)
PY

"$AW_BIN" benchmark fixture-create "$SUITE/benchmark-spec.json" "$FIXTURE"

EXECUTOR="$SUITE/executors/codex-subscription.json"
POLICY="$SUITE/policies/development.json"

"$AW_BIN" --json benchmark readiness "$SUITE/benchmark-spec.json" \
  --executor "$EXECUTOR" \
  --policy "$POLICY" > "$READINESS_JSON"

"$PYTHON" - "$READINESS_JSON" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("ready") is not True:
    for check in value.get("checks", []):
        if not check.get("passed"):
            print(f"{check.get('id')}: {check.get('detail')}", file=sys.stderr)
    raise SystemExit("BM4 readiness failed")
print("BM4 readiness: passed")
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

# Execution-only means paired model work is complete, not that the benchmark
# is complete or score-eligible. Capture the frozen visual evidence before
# scoring so completed development runs cannot become invalid only because
# the orchestration script skipped a required evidence stage.
"$AW_BIN" --json benchmark live-start "$RUN_PLAN" > "$ROOT/live-start.json"
"$AW_BIN" --json benchmark visual-capture "$RUN_PLAN" > "$ROOT/visual-capture.json"
if ! "$PYTHON" - "$ROOT/visual-capture.json" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
failures = [item for item in value.get("captures", []) if item.get("state") != "complete"]
for item in failures:
    print(
        f"BM4 visual failure: pair={item.get('pair_id')} arm={item.get('arm')} "
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
    raise SystemExit(f"BM4 visual capture failed for {len(failures)} arm(s)")
print(f"BM4 visual capture: {value.get('complete', 0)} complete; 0 harness failures")
PY
then
  "$AW_BIN" --json benchmark live-stop "$RUN_PLAN" > "$ROOT/live-stop.json" || true
  echo "BM4 model execution is preserved. Fix the visual runtime/harness and run:" >&2
  echo "  bash scripts/recover-benchmark-visual.sh $RUN_PLAN --output-root $ROOT/visual-recovery" >&2
  exit 1
fi
"$AW_BIN" --json benchmark score "$RUN_PLAN" | tee "$SCORE_JSON"
"$AW_BIN" --json benchmark consolidate "$RUN_PLAN" | tee "$CONSOLIDATE_JSON"
"$AW_BIN" --json benchmark report "$RUN_PLAN" | tee "$REPORT_JSON"
"$AW_BIN" --json benchmark live-stop "$RUN_PLAN" > "$ROOT/live-stop.json"

"$PYTHON" - "$RUN_PLAN" "$ROOT" "$SUMMARY_JSON" "$SEMANTIC_QUALIFICATION_JSON" <<'PY'
from __future__ import annotations
import json, sys
from pathlib import Path

plan_path = Path(sys.argv[1])
root = Path(sys.argv[2])
out = Path(sys.argv[3])
qualification_path = Path(sys.argv[4])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
run_dir = Path(plan["coordinator"]["run_dir"])

summary = {
    "schema": "agent-workflow/bm4-development-summary/v1",
    "run_id": plan["run_id"],
    "benchmark_id": plan["benchmark_id"],
    "claim_level": plan["claim_level"],
    "treatments": plan.get("treatments"),
    "pairs": [],
    "typesafe_qualification": {
        "qualification_path": str(qualification_path),
        "audit_path": str(root / "typesafe-api-audit.jsonl"),
        "records": 0,
        "duration_ms_total": 0.0,
        "treatment_additional_records": None,
    },
}

audit = root / "typesafe-api-audit.jsonl"
if audit.is_file():
    for line in audit.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        value = json.loads(line)
        summary["typesafe_qualification"]["records"] += 1
        duration = value.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            summary["typesafe_qualification"]["duration_ms_total"] += float(duration)
summary["typesafe_qualification"]["duration_ms_total"] = round(
    summary["typesafe_qualification"]["duration_ms_total"], 3
)

qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
total_records = summary["typesafe_qualification"]["records"]
qualification_records = int(qualification["audit_records_after"])
summary["typesafe_qualification"]["qualification_calls"] = qualification["qualification_calls"]
summary["typesafe_qualification"]["treatment_additional_records"] = total_records - qualification_records
summary["typesafe_qualification"]["treatment_includes_semantic_routing"] = False
if summary["typesafe_qualification"]["treatment_additional_records"] != 0:
    raise SystemExit(
        "BM4 treatment unexpectedly emitted additional TypeSafe calls; "
        "paired treatment identity would be contaminated"
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
        amplification = {
            "model_turn_count": 0,
            "tool_call_count": 0,
            "command_execution_count": 0,
            "launch_prompt_bytes": 0,
            "injected_context_bytes": 0,
            "injected_context_estimated_tokens": 0,
        }
        amplification_observed = False
        for phase in phases:
            timing = phase.get("timing_breakdown") or {}
            if timing.get("runner_kind") == "direct-executor":
                phase_amp = timing.get("amplification") or {}
                launch_bytes = timing.get("prompt_bytes")
                injected_bytes = 0
                injected_tokens = 0
            else:
                phase_amp = timing.get("executor_context") or {}
                launch_bytes = timing.get("agent_workflow_launch_prompt_bytes")
                injected_bytes = phase_amp.get("injected_context_bytes")
                injected_tokens = phase_amp.get("injected_context_estimated_tokens")
            for key in ("model_turn_count", "tool_call_count", "command_execution_count"):
                value = phase_amp.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    amplification[key] += int(value)
                    amplification_observed = True
            if isinstance(launch_bytes, (int, float)) and not isinstance(launch_bytes, bool):
                amplification["launch_prompt_bytes"] += int(launch_bytes)
                amplification_observed = True
            if isinstance(injected_bytes, (int, float)) and not isinstance(injected_bytes, bool):
                amplification["injected_context_bytes"] += int(injected_bytes)
            if isinstance(injected_tokens, (int, float)) and not isinstance(injected_tokens, bool):
                amplification["injected_context_estimated_tokens"] += int(injected_tokens)
        if not amplification_observed:
            amplification = None

        item["arms"][arm_name] = {
            "treatment_id": plan["treatments"][arm_name]["treatment_id"],
            "state": arm_value.get("state"),
            "machine_score": score_value.get("machine_score"),
            "machine_score_eligibility": (score_value.get("eligibility") or {}).get("state"),
            "usage": arm_value.get("usage"),
            "amplification": amplification,
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
    for field in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        left = (control.get("usage") or {}).get(field)
        right = (candidate.get("usage") or {}).get(field)
        deltas[field] = (
            float(right) - float(left)
            if isinstance(left, (int, float)) and not isinstance(left, bool)
            and isinstance(right, (int, float)) and not isinstance(right, bool)
            else None
        )
    for field in (
        "model_turn_count",
        "tool_call_count",
        "command_execution_count",
        "launch_prompt_bytes",
        "injected_context_bytes",
        "injected_context_estimated_tokens",
    ):
        left = (control.get("amplification") or {}).get(field)
        right = (candidate.get("amplification") or {}).get(field)
        deltas[field] = (
            float(right) - float(left)
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
print(f"BM4 summary: {out}")
print(
    "TypeSafe audit: "
    f"{summary['typesafe_qualification']['records']} calls; "
    f"{summary['typesafe_qualification']['duration_ms_total']} ms total; "
    "treatment additional calls=0"
)
PY

"$PYTHON" "$REPO_ROOT/scripts/collect-value-smoke-evidence.py" "$ROOT" --output "$EVIDENCE_ARCHIVE"

if [[ -n "$RESULTS_REPO_ARG" ]]; then
  RESULTS_REPO="$("$PYTHON" - "$RESULTS_REPO_ARG" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
else
  RESULTS_REPO="$(cd "$REPO_ROOT/.." && pwd)/agent-workflow-benchmark-results"
fi

if [[ -d "$RESULTS_REPO/.git" ]]; then
  "$PYTHON" "$REPO_ROOT/scripts/prepare-bm4-publication.py"     --plan "$RUN_PLAN"     --root "$ROOT"     --destination "$RESULTS_REPO/bm4"     --private-archive "$EVIDENCE_ARCHIVE"
  echo "BM4 sanitized publication copied to: $RESULTS_REPO/bm4"
else
  echo "warning: benchmark results repo not found; public BM4 tree not copied: $RESULTS_REPO" >&2
fi

echo
echo "BM4 development run complete"
echo "  root:     $ROOT"
echo "  summary:  $SUMMARY_JSON"
echo "  score:    $SCORE_JSON"
echo "  consolidate: $CONSOLIDATE_JSON"
echo "  report:   $REPORT_JSON"
echo "  semantic: $SEMANTIC_QUALIFICATION_JSON"
echo "  audit:    $AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"
echo "  evidence: $EVIDENCE_ARCHIVE"
echo "  public results: $RESULTS_REPO/bm4"
echo
echo "Do not treat a development run as a generalized treatment-effect claim."
