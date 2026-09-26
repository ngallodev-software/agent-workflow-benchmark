#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$AW"
ds_require_executable "$PYTHON"
ds_verify_source_corpus
ds_verify_p1_passed

[[ ! -e "$P2_RUN" ]] || ds_die "P2 run already exists: $P2_RUN"
mkdir -p "$P2_ROOT"
chmod 700 "$P2_ROOT"

echo "Running full preregistered 120-case inference with no oracle argument..."
"$AW" benchmark decision-study-run "$SOURCE_CORPUS" "$P2_RUN"

"$PYTHON" - "$P2_RUN/run-manifest.json" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
assert value["counts"]["cases"] == 120, value["counts"]
assert value["oracle_seen_during_inference"] is False
assert "oracle" not in value.get("files", {})
assert value["identity"]["question_set_version"] == "routing/v2"
assert value["identity"]["projector_version"] == "routing-state/v2"
print("P2 inference manifest checks: pass")
PY

echo "P2 inference complete: $P2_RUN"
echo "Next: bash scripts/decision-study/p2-report.sh"
