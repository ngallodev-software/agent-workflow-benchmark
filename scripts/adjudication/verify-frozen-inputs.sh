#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

echo "Verifying frozen routing-semantic-v1 inputs..."
aw_verify_frozen_inputs
echo "Frozen inputs verified."
