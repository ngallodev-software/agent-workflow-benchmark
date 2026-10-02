#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
command -v git >/dev/null 2>&1 || aj_die "git is required"

ROOT="${AGENTIC_JEV_SWE_MANAGER_ROOT:-$AGENTIC_JEV_ROOT/swe-manager-v1}"
CHECKOUT="$ROOT/inspect_evals"
COHORT="$ROOT/cohort.json"
PRIOR="${AGENTIC_JEV_PRIOR_EXTERNAL_COHORT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1/cohort.json}"
PIN="190dfa27bc2e9b3e966ea6e8a682626d55b513c0"
URL="https://github.com/UKGovernmentBEIS/inspect_evals.git"

mkdir -p "$ROOT"
chmod 700 "$ROOT"
[[ ! -e "$COHORT" ]] || aj_die "paired cohort already frozen: $COHORT"
aj_require_file "$PRIOR"

if [[ -d "$CHECKOUT/.git" ]]; then
  observed="$(git -C "$CHECKOUT" rev-parse HEAD)"
  [[ "$observed" == "$PIN" ]] || aj_die "Inspect Evals checkout has wrong commit: $observed"
elif [[ -e "$CHECKOUT" ]]; then
  aj_die "Inspect Evals checkout path exists but is not a git repository: $CHECKOUT"
else
  tmp="$ROOT/.inspect_evals.tmp.$$"
  trap 'rm -rf "$tmp"' EXIT
  git clone --quiet --no-checkout "$URL" "$tmp"
  git -C "$tmp" checkout --quiet --detach "$PIN"
  mv "$tmp" "$CHECKOUT"
  trap - EXIT
fi

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - "$CHECKOUT" "$PRIOR" "$COHORT" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v1 import freeze_swe_manager_cohort

checkout, prior, destination = map(Path, sys.argv[1:])
result = freeze_swe_manager_cohort(
    inspect_evals_checkout=checkout,
    prior_cohort_path=prior,
    destination=destination,
)
print("Frozen fresh SWE-Lancer manager cohort")
print("tasks:", len(result["tasks"]))
print("excluded_previous:", len(result["selection"]["previously_observed_ids"]))
print("inspect_evals_commit:", result["source"]["commit"])
print("cohort_sha256:", result["sha256"])
print("artifact:", result["path"])
PY
