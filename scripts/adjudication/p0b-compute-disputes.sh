#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

A_PASS="$ORACLE_RUN/a/output/adjudication.json"
B_PASS="$ORACLE_RUN/b/output/adjudication.json"
aw_require_file "$A_PASS"
aw_require_file "$B_PASS"

if [[ -e "$DISPUTE_VIEW" ]]; then
  aw_die "dispute view already exists: $DISPUTE_VIEW"
fi

"$AW" benchmark decision-study-oracle-disputes   "$ORACLE_VIEW"   "$A_PASS"   "$B_PASS"   "$DISPUTE_VIEW"

echo "Dispute view: $DISPUTE_VIEW"
echo "requires_c: $(aw_dispute_requires_c)"
