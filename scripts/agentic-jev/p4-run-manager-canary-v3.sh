#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_die "v3 manager canary retired: v2 control already exercised the same Noul+Score second-order Jev pathway. Run p4-audit-v2-manager-traces.sh against the preserved six-task v2 manager evidence instead."
