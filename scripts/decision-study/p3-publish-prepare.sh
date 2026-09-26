#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$AW"
ds_require_file "$FROZEN_ORACLE"
ds_require_file "$P2_RUN/run-manifest.json"

[[ ! -e "$P3_PUBLIC" ]] || ds_die "P3 publication tree already exists: $P3_PUBLIC"
mkdir -p "$P3_ROOT"
chmod 700 "$P3_ROOT"

"$AW" benchmark decision-study-publish-prepare "$P2_RUN" "$FROZEN_ORACLE" "$P3_PUBLIC"

echo "Sanitized publication tree prepared: $P3_PUBLIC"
echo "Review it before copying anything into benchmark-results or the portfolio site."
