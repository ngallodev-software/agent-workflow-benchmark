#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

echo "routing-semantic-v1 adjudication workflow"
echo "Private root: $PRIVATE_ROOT"

if [[ ! -f "$QUALIFICATION" ]]; then
  echo
  echo "No P0A qualification exists; running P0A first."
  "$SCRIPT_DIR/p0a-qualify.sh"
elif aw_qualification_model >/dev/null 2>&1; then
  echo
  echo "Existing passing P0A qualification found; verifying without regenerating it."
  "$SCRIPT_DIR/verify-qualification.sh"
else
  echo
  echo "Existing P0A qualification is incomplete or invalid; archiving and rerunning P0A."
  "$SCRIPT_DIR/p0a-qualify.sh"
fi

echo
"$SCRIPT_DIR/p0b-run-ab.sh"

echo
"$SCRIPT_DIR/p0b-validate-ab.sh"

echo
"$SCRIPT_DIR/p0b-compute-disputes.sh"

echo
"$SCRIPT_DIR/p0b-run-c.sh"

echo
"$SCRIPT_DIR/p0b-freeze.sh"

echo
"$SCRIPT_DIR/p0b-validate-oracle.sh"

echo
echo "Oracle workflow complete."
echo "Oracle: $ORACLE_RUN/oracle.json"
