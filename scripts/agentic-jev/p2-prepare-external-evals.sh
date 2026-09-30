#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
aj_require_file "$AGENTIC_JEV_RUNTIME_LOCK"

EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"

[[ -d "$CHECKOUT/.git" ]] || aj_die "run p2-freeze-external-cohort.sh first"

"$PYTHON" -m pip install   "inspect-ai==0.3.268"   "inspect-swe==0.2.71"   "typesafe-sdk==0.6.0"   "pandas"   "python-dotenv"   "$CHECKOUT[swe_bench,swe_lancer]"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -   "$AGENTIC_JEV_RUNTIME_LOCK" <<'PY'
import sys
from pathlib import Path
from agent_workflow_benchmark.benchmarking.agentic_jev import load_agentic_jev_runtime_lock

lock = load_agentic_jev_runtime_lock(Path(sys.argv[1]))
print("External eval dependencies installed; frozen Agentic Jev runtime still validates")
print("codex:", lock["codex_cli"]["resolved"])
print("inspect_ai:", lock["inspect_ai_version"])
print("inspect_swe:", lock["inspect_swe_version"])
print("model:", lock["agent_model"])
PY
