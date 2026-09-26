#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

"$SCRIPT_DIR/verify-qualification.sh"
aw_resolve_adjudication_model
"$SCRIPT_DIR/verify-frozen-inputs.sh"

requires_c="$(aw_dispute_requires_c)"
if [[ "$requires_c" != "true" ]]; then
  echo "No C adjudication required."
  exit 0
fi

C_PASS="$ORACLE_RUN/c/output/adjudication.json"
if [[ -e "$C_PASS" ]]; then
  aw_die "C adjudication already exists: $C_PASS"
fi

echo "Running independent C tiebreaker with $ADJUDICATION_MODEL..."
"$AW" benchmark adjudication-inspect-run-c   "$MODULE"   "$DISPUTE_VIEW"   "$ORACLE_PROTOCOL"   "$RUNTIME_LOCK"   "$QUALIFICATION"   "$ORACLE_RUN"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"

"$AW" benchmark decision-study-adjudication-validate "$DISPUTE_VIEW" "$C_PASS"
echo "C adjudication completed and validated: $C_PASS"
