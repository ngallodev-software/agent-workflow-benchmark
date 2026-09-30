#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_RUNTIME_LOCK"
aj_require_file "$AGENTIC_JEV_QUALIFICATION"

EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"
COHORT="$EXTERNAL_ROOT/cohort.json"
V2_ROOT="${AGENTIC_JEV_DECISION_V2_ROOT:-$AGENTIC_JEV_ROOT/decision-skill-v2}"
V2_LOCK="$V2_ROOT/runtime-lock.json"

aj_require_file "$COHORT"
[[ -d "$CHECKOUT/.git" ]] || aj_die "missing pinned Inspect Evals checkout: $CHECKOUT"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$V2_LOCK"   "$AGENTIC_JEV_RUNTIME_LOCK"   "$AGENTIC_JEV_QUALIFICATION"   "$COHORT"   "$CHECKOUT" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v2 import (
    create_decision_v2_lock,
)

destination, base_lock, bridge_qualification, cohort, checkout = sys.argv[1:]
result = create_decision_v2_lock(
    destination=Path(destination),
    base_runtime_lock_path=Path(base_lock),
    bridge_qualification_path=Path(bridge_qualification),
    cohort_path=Path(cohort),
    inspect_evals_checkout=Path(checkout),
)
print("Agentic Jev decision-skill v2 treatment frozen")
print("upstream_skill_sha256:", result["skills"]["upstream_typesafe_sha256"])
print("decision_skill_sha256:", result["skills"]["decision_support_sha256"])
print("model:", result["runtime"]["model"])
print("codex:", result["runtime"]["codex_version"])
print(result["path"])
PY
