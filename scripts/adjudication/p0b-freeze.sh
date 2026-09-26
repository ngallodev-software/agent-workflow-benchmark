#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

A_PASS="$ORACLE_RUN/a/output/adjudication.json"
B_PASS="$ORACLE_RUN/b/output/adjudication.json"
ORACLE="$ORACLE_RUN/oracle.json"

aw_require_file "$A_PASS"
aw_require_file "$B_PASS"
aw_require_file "$DISPUTE_VIEW"

if [[ -e "$ORACLE" ]]; then
  aw_die "oracle already exists: $ORACLE"
fi

args=(
  benchmark decision-study-oracle-freeze
  "$ORACLE_VIEW"
  "$A_PASS"
  "$B_PASS"
  "$ORACLE"
  --oracle-version routing-semantic-oracle-v1.0.0
)

if [[ "$(aw_dispute_requires_c)" == "true" ]]; then
  C_PASS="$ORACLE_RUN/c/output/adjudication.json"
  aw_require_file "$C_PASS"
  args+=(--c-view "$DISPUTE_VIEW" --c-pass "$C_PASS")
fi

if [[ -n "${RESOLUTIONS:-}" ]]; then
  aw_require_file "$RESOLUTIONS"
  args+=(--resolutions "$RESOLUTIONS")
fi

"$AW" "${args[@]}"

echo "Frozen oracle: $ORACLE"
echo "Manifest: $ORACLE.manifest.json"
