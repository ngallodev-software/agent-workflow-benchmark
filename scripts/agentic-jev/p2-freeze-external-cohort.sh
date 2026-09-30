#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"
command -v git >/dev/null 2>&1 || {
  echo "git is required for external eval source freeze" >&2
  exit 2
}

INSPECT_EVALS_REPO="https://github.com/UKGovernmentBEIS/inspect_evals.git"
INSPECT_EVALS_COMMIT="b49df6bc9e30b2d24571084bc710b9439b9ffa77"
EXTERNAL_ROOT="${AGENTIC_JEV_EXTERNAL_ROOT:-$AGENTIC_JEV_ROOT/external-eval-scout-v1}"
CHECKOUT="$EXTERNAL_ROOT/inspect_evals"
MANIFEST="$EXTERNAL_ROOT/cohort.json"
PRIOR_MANIFEST="$AGENTIC_JEV_RUN/run-manifest.json"

mkdir -p "$EXTERNAL_ROOT"
chmod 700 "$EXTERNAL_ROOT"

if [[ -e "$MANIFEST" ]]; then
  echo "external-eval cohort already frozen: $MANIFEST" >&2
  exit 2
fi

if [[ -d "$CHECKOUT/.git" ]]; then
  observed="$(git -C "$CHECKOUT" rev-parse HEAD)"
  if [[ "$observed" != "$INSPECT_EVALS_COMMIT" ]]; then
    echo "existing inspect_evals checkout is not at frozen commit: $observed" >&2
    exit 2
  fi
elif [[ -e "$CHECKOUT" ]]; then
  echo "external eval checkout path exists but is not a git checkout: $CHECKOUT" >&2
  exit 2
else
  tmp="$EXTERNAL_ROOT/.inspect_evals.tmp.$$"
  trap 'rm -rf "$tmp"' EXIT
  git clone --quiet --no-checkout "$INSPECT_EVALS_REPO" "$tmp"
  git -C "$tmp" checkout --quiet --detach "$INSPECT_EVALS_COMMIT"
  mv "$tmp" "$CHECKOUT"
  trap - EXIT
fi

observed="$(git -C "$CHECKOUT" rev-parse HEAD)"
[[ "$observed" == "$INSPECT_EVALS_COMMIT" ]] || {
  echo "inspect_evals source identity mismatch: $observed" >&2
  exit 2
}

"$PYTHON" "$SCRIPT_DIR/p2-select-external-cohort.py"   "$CHECKOUT"   "$MANIFEST"   "$PRIOR_MANIFEST"
