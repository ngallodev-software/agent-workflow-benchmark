#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$AW"
ds_require_file "$SOURCE_CORPUS"
ds_require_file "$FROZEN_ORACLE"
ds_require_file "$P2_RUN/run-manifest.json"

"$AW" benchmark decision-study-validate "$SOURCE_CORPUS" --oracle "$FROZEN_ORACLE"
"$AW" benchmark decision-study-report "$P2_RUN" "$FROZEN_ORACLE"

echo "P2 report generated under: $P2_RUN"
echo "Inspect decision-study-report.json, decision-study-report.md, exclusions.jsonl, and denominators before publication."
