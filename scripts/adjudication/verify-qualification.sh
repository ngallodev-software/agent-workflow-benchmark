#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

aw_require_executable "$AW"
aw_require_file "$MODULE"
aw_require_file "$RUNTIME_LOCK"
aw_require_file "$QUALIFICATION"

echo "Validating adjudication module..."
"$AW" benchmark adjudication-module-validate "$MODULE" >/dev/null

echo "Verifying P0A qualification, IA-1 through IA-8, module hash, runtime-lock hash, and IA-2 model..."
aw_resolve_adjudication_model

"$PYTHON" - "$QUALIFICATION" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"qualified: {value['qualified']}")
for gate in [f"IA-{n}" for n in range(1, 9)]:
    print(f"{gate}: {value['gates'][gate]['status']}")
print(f"IA-2 model: {value['gates']['IA-2']['evidence']['model']}")
PY

echo "P0A qualification verified."
