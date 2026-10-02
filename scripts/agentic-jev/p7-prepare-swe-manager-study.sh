#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
ROOT="\${AGENTIC_JEV_SWE_MANAGER_ROOT:-$AGENTIC_JEV_ROOT/swe-manager-v1}"
CHECKOUT="$ROOT/inspect_evals"
COHORT="$ROOT/cohort.json"
aj_require_file "$COHORT"
[[ -d "$CHECKOUT/.git" ]] || aj_die "run p7-freeze-swe-manager-study.sh first"

"$PYTHON" -m pip install "$CHECKOUT[swe_lancer]"

PYTHONPATH="$BENCH_REPO/src:$CHECKOUT/src\${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - "$COHORT" "$CHECKOUT" <<'PY'
import sys
from importlib import metadata
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v1 import load_swe_manager_cohort

if metadata.version("agent-workflow-comparative-eval") != "0.3.2":
    raise SystemExit("agent-workflow-comparative-eval==0.3.2 is required")
cohort = load_swe_manager_cohort(Path(sys.argv[1]), inspect_evals_checkout=Path(sys.argv[2]))
print("Paired SWE-Lancer dependencies ready")
print("comparative_eval:", metadata.version("agent-workflow-comparative-eval"))
print("inspect_ai:", metadata.version("inspect-ai"))
print("inspect_evals:", metadata.version("inspect-evals"))
print("tasks:", len(cohort["tasks"]))
PY
