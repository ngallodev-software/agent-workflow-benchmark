#!/usr/bin/env bash

aw_die() {
  echo "error: $*" >&2
  return 1
}

aw_require_file() {
  [[ -f "$1" ]] || aw_die "required file not found: $1"
}

aw_require_executable() {
  [[ -x "$1" ]] || aw_die "required executable not found: $1"
}

aw_qualification_model() {
  aw_require_executable "$PYTHON"
  aw_require_file "$QUALIFICATION"
  aw_require_file "$MODULE"
  aw_require_file "$RUNTIME_LOCK"

  "$PYTHON" - "$QUALIFICATION" "$MODULE" "$RUNTIME_LOCK" <<'PY'
import hashlib
import json
import sys

qualification_path, module_path, runtime_lock_path = sys.argv[1:4]

def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

q = load(qualification_path)
if q.get("qualified") is not True:
    raise SystemExit("qualification manifest does not report qualified=true")

required = [f"IA-{n}" for n in range(1, 9)]
gates = q.get("gates") or {}
missing = [gate for gate in required if gate not in gates]
failed = [
    gate
    for gate in required
    if gate in gates and (gates[gate] or {}).get("status") != "pass"
]
if missing or failed:
    raise SystemExit(
        f"qualification gates are not all passing; missing={missing}, failed={failed}"
    )

if q.get("module_sha256") != sha256(module_path):
    raise SystemExit("qualification module_sha256 does not match module bytes")
if q.get("runtime_lock_sha256") != sha256(runtime_lock_path):
    raise SystemExit("qualification runtime_lock_sha256 does not match runtime lock bytes")

model = (
    gates.get("IA-2", {})
    .get("evidence", {})
    .get("model")
)
if not isinstance(model, str) or not model:
    raise SystemExit("qualification IA-2 does not record a model")

print(model)
PY
}

aw_resolve_adjudication_model() {
  local qualified_model requested_from_id
  qualified_model="$(aw_qualification_model)" || return

  if [[ -n "${MODEL_ID:-}" ]]; then
    requested_from_id="openai-api/codex-lb/$MODEL_ID"
    if [[ "$requested_from_id" != "$qualified_model" ]]; then
      aw_die "MODEL_ID selects $requested_from_id but P0A qualified $qualified_model"
      return
    fi
  fi

  if [[ -n "${ADJUDICATION_MODEL:-}" && "$ADJUDICATION_MODEL" != "$qualified_model" ]]; then
    aw_die "ADJUDICATION_MODEL=$ADJUDICATION_MODEL but P0A qualified $qualified_model"
    return
  fi

  export ADJUDICATION_MODEL="$qualified_model"
  export MODEL_ID="${qualified_model##*/}"

  if ! declare -p ADJUDICATION_MODEL_ARGS >/dev/null 2>&1; then
    ADJUDICATION_MODEL_ARGS=(--model-arg responses_api=true)
  fi

  echo "Qualified adjudication model: $ADJUDICATION_MODEL"
}

aw_verify_frozen_inputs() {
  aw_require_file "$ORACLE_VIEW"
  aw_require_file "$CORPUS"

  "$PYTHON" - "$ORACLE_VIEW" "$CORPUS" <<'PY'
import hashlib
import sys

expected = {
    sys.argv[1]: "a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a",
    sys.argv[2]: "e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280",
}

for path, wanted in expected.items():
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    observed = h.hexdigest()
    print(f"{observed}  {path}")
    if observed != wanted:
        raise SystemExit(
            f"frozen input hash mismatch for {path}: observed {observed}, expected {wanted}"
        )
PY
}

aw_dispute_requires_c() {
  aw_require_file "$DISPUTE_VIEW"
  "$PYTHON" - "$DISPUTE_VIEW" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print("true" if value.get("requires_c") is True else "false")
PY
}

aw_oracle_run_must_be_new() {
  if [[ -d "$ORACLE_RUN" ]] && find "$ORACLE_RUN" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    aw_die "ORACLE_RUN already contains files; choose a new ORACLE_RUN: $ORACLE_RUN"
    return
  fi
}
