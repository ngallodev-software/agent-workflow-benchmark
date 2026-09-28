#!/usr/bin/env bash
aj_die() { echo "error: $*" >&2; return 1; }

aj_require_file() {
  local path="${1:-}"
  [[ -n "$path" && -f "$path" ]] || aj_die "required file not found: $path"
}

aj_require_executable() {
  local path="${1:-}"
  [[ -n "$path" && -x "$path" ]] || aj_die "required executable not found: $path"
}

aj_require_model() {
  [[ -n "${AGENTIC_JEV_MODEL:-}" ]] || aj_die "set AGENTIC_JEV_MODEL explicitly before freezing the pilot runtime"
}

aj_require_typesafe_key() {
  [[ -n "${TYPESAFE_API_KEY:-}" ]] || aj_die "TYPESAFE_API_KEY must be present on the host for live Jev qualification/run"
}
