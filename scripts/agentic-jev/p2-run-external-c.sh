#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_RUNTIME_LOCK"
aj_require_file "$AGENTIC_JEV_QUALIFICATION"
aj_require_typesafe_key

EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"
COHORT="$EXTERNAL_ROOT/cohort.json"
RUN_ROOT="$EXTERNAL_ROOT/c-run-manager"
PRIOR_MANIFEST="$AGENTIC_JEV_RUN/run-manifest.json"

aj_require_file "$COHORT"
aj_require_file "$PRIOR_MANIFEST"
[[ -d "$CHECKOUT/.git" ]] || aj_die "missing pinned Inspect Evals checkout: $CHECKOUT"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$RUN_ROOT"   "$COHORT"   "$CHECKOUT"   "$PRIOR_MANIFEST"   "$AGENTIC_JEV_RUNTIME_LOCK"   "$AGENTIC_JEV_QUALIFICATION" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_external import (
    run_external_jev_scout,
)

run_root, cohort, checkout, prior, lock, qualification = sys.argv[1:]
result = run_external_jev_scout(
    output_root=Path(run_root),
    cohort_path=Path(cohort),
    inspect_evals_checkout=Path(checkout),
    prior_manifest_path=Path(prior),
    runtime_lock_path=Path(lock),
    qualification_path=Path(qualification),
)
execution = result["execution"]
print("Agentic Jev external-eval manager C-arm gate complete")
print("samples:", execution["samples_observed"])
print("success:", execution["success"])
print("errors:", execution["errors"])
print("jev_calls:", execution["jev_tool_calls"])
print("samples_with_jev_calls:", execution["samples_with_jev_calls"])
print(result["path"])
PY
