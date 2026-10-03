#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_typesafe_key

ROOT="${AGENTIC_JEV_SWE_MANAGER_V2_ROOT:-$AGENTIC_JEV_ROOT/swe-manager-v2}"
CHECKOUT="$ROOT/inspect_evals"
COHORT="$ROOT/cohort.json"
RUN_ROOT="${AGENTIC_JEV_SWE_MANAGER_V2_RUN_ROOT:-$ROOT/paired-run}"
aj_require_file "$COHORT"
[[ -d "$CHECKOUT/.git" ]] || aj_die "missing frozen Inspect Evals checkout"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - \
  "$RUN_ROOT" "$COHORT" "$CHECKOUT" "${AGENTIC_JEV_JEV_MODEL:-}" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2_study import (
    run_paired_swe_manager_v2_study,
)
root, cohort, checkout, jev_model = sys.argv[1:]
result = run_paired_swe_manager_v2_study(
    output_root=Path(root),
    cohort_path=Path(cohort),
    inspect_evals_checkout=Path(checkout),
    jev_model=jev_model or None,
)
report = result["report"]
print("Paired SWE-Lancer Luna/Jev v2 study complete")
print("paired_n:", report["paired_n"])
print("control_accuracy:", report["primary"]["control"]["accuracy"])
print("treatment_accuracy:", report["primary"]["treatment"]["accuracy"])
print("delta:", report["primary"]["treatment_minus_control_accuracy"])
print("discordant:", report["discordant_pairs"])
print("jev_exposure:", report["jev_exposure"])
print("artifact:", result["path"])
PY
