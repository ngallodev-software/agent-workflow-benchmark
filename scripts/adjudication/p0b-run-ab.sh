#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

# A. Verify the existing P0A qualification as an independent script.
bash "$SCRIPT_DIR/verify-qualification.sh"

# B. env.sh above established all study paths. Resolve the model from the
# qualification so P0B cannot silently drift from P0A.
aw_resolve_adjudication_model

# C. Re-check frozen authoring-view and corpus bytes.
bash "$SCRIPT_DIR/verify-frozen-inputs.sh"

# D. Start real independent A/B oracle adjudication.
aw_require_file "$ORACLE_PROTOCOL"
aw_oracle_run_must_be_new
mkdir -p "$ORACLE_RUN"

echo
echo "Starting real independent A/B adjudication."
echo "Model: $ADJUDICATION_MODEL"
echo "Output: $ORACLE_RUN"

"$AW" benchmark adjudication-inspect-run-primary   "$MODULE"   "$ORACLE_VIEW"   "$ORACLE_PROTOCOL"   "$RUNTIME_LOCK"   "$QUALIFICATION"   "$ORACLE_RUN"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"

echo
echo "A/B adjudication completed."
echo "A: $ORACLE_RUN/a/output/adjudication.json"
echo "B: $ORACLE_RUN/b/output/adjudication.json"
