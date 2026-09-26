#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ORACLE="$ORACLE_RUN/oracle.json"
aw_require_file "$ORACLE"

"$AW" benchmark decision-study-validate "$CORPUS" --oracle "$ORACLE"
echo "Final oracle validated: $ORACLE"
