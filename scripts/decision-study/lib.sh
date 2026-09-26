#!/usr/bin/env bash
set -Eeuo pipefail

DS_EXPECTED_CORPUS_SHA256="e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280"
DS_STUDY_ID="routing-semantic-v1"
DS_DATASET_VERSION="routing-semantic-corpus-v1.0.0"
DS_QUESTION_SET="routing/v2"
DS_PROJECTOR="routing-state/v2"

ds_die() {
  echo "error: $*" >&2
  return 1
}

ds_require_file() {
  local path="${1:-}"
  [[ -n "$path" ]] || ds_die "required path is unset"
  [[ -f "$path" ]] || ds_die "required file not found: $path"
}

ds_require_executable() {
  local path="${1:-}"
  [[ -n "$path" ]] || ds_die "required executable is unresolved"
  [[ -x "$path" ]] || ds_die "required executable not found: $path"
}

ds_sha256() {
  sha256sum "$1" | awk '{print $1}'
}

ds_verify_source_corpus() {
  ds_require_file "$SOURCE_CORPUS"
  local actual
  actual="$(ds_sha256 "$SOURCE_CORPUS")"
  [[ "$actual" == "$DS_EXPECTED_CORPUS_SHA256" ]] ||     ds_die "frozen corpus SHA-256 mismatch: expected $DS_EXPECTED_CORPUS_SHA256, got $actual"
  echo "Frozen corpus verified: $actual"
}

ds_verify_p1_passed() {
  ds_require_file "$P1_VERIFICATION"
  "$PYTHON" - "$P1_VERIFICATION" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
if value.get("status") != "pass":
    raise SystemExit("P1 verification is not passing")
print("P1 verification: pass")
PY
}
