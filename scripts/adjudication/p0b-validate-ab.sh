#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

A_PASS="$ORACLE_RUN/a/output/adjudication.json"
B_PASS="$ORACLE_RUN/b/output/adjudication.json"
aw_require_file "$A_PASS"
aw_require_file "$B_PASS"

"$AW" benchmark decision-study-adjudication-validate "$ORACLE_VIEW" "$A_PASS"
"$AW" benchmark decision-study-adjudication-validate "$ORACLE_VIEW" "$B_PASS"

echo "A/B adjudication passes validated."
