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

  if [[ ! -f "$RESOLUTIONS" ]]; then
    echo "No recorded three-way resolution artifact exists; preparing one from A/B/C..."
    bash "$SCRIPT_DIR/p0b-prepare-resolutions.sh"
  fi

  aw_require_file "$RESOLUTIONS"

  read -r resolution_count unresolved_count todo_count < <(
    "$PYTHON" - "$RESOLUTIONS" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
records = value.get("records", [])
unresolved = sum(item.get("status") == "unresolved" for item in records)
todo = sum(
    str(item.get("rationale", "")).strip().startswith("TODO:")
    for item in records
)
print(len(records), unresolved, todo)
PY
  )

  if [[ "$todo_count" -gt 0 ]]; then
    aw_die "$todo_count three-way resolution record(s) still contain TODO rationale text. Review $RESOLUTION_REVIEW and edit $RESOLUTIONS before freezing."
  fi

  if [[ "$unresolved_count" -gt 0 && "${ALLOW_UNRESOLVED_RESOLUTIONS:-0}" != "1" ]]; then
    aw_die "$unresolved_count three-way conflict(s) are explicitly unresolved. Resolve them, or set ALLOW_UNRESOLVED_RESOLUTIONS=1 only if the study intentionally preserves unresolved oracle conflicts."
  fi

  if [[ "$resolution_count" -gt 0 ]]; then
    args+=(--resolutions "$RESOLUTIONS")
  fi
fi

"$AW" "${args[@]}"

echo "Frozen oracle: $ORACLE"
echo "Manifest: $ORACLE.manifest.json"
