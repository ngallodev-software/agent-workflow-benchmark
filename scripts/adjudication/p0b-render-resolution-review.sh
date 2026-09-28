#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aw_require_executable "$PYTHON"
aw_require_file "$RESOLUTION_REVIEW"

"$PYTHON" -m agent_workflow_benchmark.benchmarking.resolution_review \
  "$RESOLUTION_REVIEW" \
  "$RESOLUTION_REVIEW_MD" \
  "${ORACLE_REVIEW_GUIDE:-}"

echo "Human review: $RESOLUTION_REVIEW_MD"
