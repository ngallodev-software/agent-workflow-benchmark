#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
ROOT="${AGENTIC_JEV_SWE_MANAGER_V2_ROOT:-$AGENTIC_JEV_ROOT/swe-manager-v2}"
RUN_ROOT="${AGENTIC_JEV_SWE_MANAGER_V2_RUN_ROOT:-$ROOT/paired-run}"
PUBLIC_ROOT="${AGENTIC_JEV_SWE_MANAGER_V2_PUBLIC_ROOT:-$ROOT/publication}"

aj_require_file "$RUN_ROOT/run-manifest.json"
[[ ! -e "$PUBLIC_ROOT" ]] || aj_die "publication destination already exists: $PUBLIC_ROOT"

PYTHONPATH="$BENCH_REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m \
  agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2_publication \
  "$RUN_ROOT" "$PUBLIC_ROOT"

echo "Review the sanitized v2 publication tree before copying it into benchmark-results."
