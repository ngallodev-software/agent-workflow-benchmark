#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$AW"
ds_require_file "$P1_CORPUS"
ds_require_file "$P1_SELECTION"

[[ ! -e "$P1_RUN" ]] || ds_die "P1 run already exists: $P1_RUN"

echo "Running development-only P1 smoke with no oracle argument..."
"$AW" benchmark decision-study-run "$P1_CORPUS" "$P1_RUN"

echo "P1 inference run complete: $P1_RUN"
