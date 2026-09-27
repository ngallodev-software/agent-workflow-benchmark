#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "P3/2 — prepare sanitized publication tree"
bash "$SCRIPT_DIR/p3-publish-prepare.sh"

echo
echo "P3/2 — verify publication privacy, integrity, and full-study identity"
bash "$SCRIPT_DIR/p3-verify-public.sh"

echo
echo "P3 publication bundle is verified locally."
echo "Review the aggregate claims before copying the tree into benchmark-results or the portfolio site."
