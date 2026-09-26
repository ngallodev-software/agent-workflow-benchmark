#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

# P0A selects the adjudicator model for the cohort. Environment variables are
# explicit overrides; otherwise use the current study default.
if [[ -n "${ADJUDICATION_MODEL:-}" ]]; then
  case "$ADJUDICATION_MODEL" in
    openai-api/codex-lb/*)
      _model_from_full="${ADJUDICATION_MODEL##*/}"
      if [[ -n "${MODEL_ID:-}" && "$MODEL_ID" != "$_model_from_full" ]]; then
        aw_die "MODEL_ID=$MODEL_ID conflicts with ADJUDICATION_MODEL=$ADJUDICATION_MODEL"
      fi
      MODEL_ID="${MODEL_ID:-$_model_from_full}"
      ;;
    *)
      aw_die "ADJUDICATION_MODEL must use openai-api/codex-lb/<model-id>"
      ;;
  esac
else
  MODEL_ID="${MODEL_ID:-deepseek-flash}"
  ADJUDICATION_MODEL="openai-api/codex-lb/$MODEL_ID"
fi
export MODEL_ID ADJUDICATION_MODEL
ADJUDICATION_MODEL_ARGS=(--model-arg responses_api=true)

QUALIFICATION_ROOT="$PRIVATE_ROOT/inspect-qualification"
RUN_LOG="$PRIVATE_ROOT/p0a-qualify-last.log"

aw_require_executable "$AW"
aw_require_executable "$PYTHON"
aw_require_file "$MODULE"
command -v curl >/dev/null 2>&1 || aw_die "curl is required"
command -v docker >/dev/null 2>&1 || aw_die "docker is required"

echo "Checking pinned Inspect runtime versions..."
"$PYTHON" - <<'PY'
from importlib import metadata

required = {
    "inspect-ai": "0.3.268",
    "inspect-swe": "0.2.70",
}
for name, expected in required.items():
    try:
        observed = metadata.version(name)
    except metadata.PackageNotFoundError as exc:
        raise SystemExit(
            f"{name} is not installed; install agent-workflow-benchmark[inspect]"
        ) from exc
    print(f"{name}: {observed}")
    if observed != expected:
        raise SystemExit(f"{name}: observed {observed}; expected {expected}")
PY

echo
echo "Checking codex-lb at $CODEX_LB_BASE_URL ..."
MODELS_JSON="$(mktemp)"
trap 'rm -f "$MODELS_JSON"' EXIT
curl -fsS "$CODEX_LB_BASE_URL/models" >"$MODELS_JSON"

"$PYTHON" - "$MODELS_JSON" "$MODEL_ID" <<'PY'
import json
import sys

path, wanted = sys.argv[1], sys.argv[2]
value = json.load(open(path, encoding="utf-8"))
models = sorted(
    item["id"]
    for item in value.get("data", [])
    if isinstance(item, dict) and isinstance(item.get("id"), str)
)
print("Available models:")
for model in models:
    print(f"  {model}")
if wanted not in models:
    raise SystemExit(
        f"required adjudication model {wanted!r} was not returned by codex-lb /models"
    )
print(f"Selected adjudication model: {wanted}")
PY

echo
echo "Inspect model: $ADJUDICATION_MODEL"
echo "Validating Inspect adjudication module..."
"$AW" benchmark adjudication-module-validate "$MODULE"

echo
if [[ -f "$RUNTIME_LOCK" ]]; then
  echo "Reusing frozen runtime lock (model selection is qualified separately):"
  echo "  $RUNTIME_LOCK"
else
  echo "Creating frozen runtime lock..."
  "$AW" benchmark adjudication-inspect-runtime-lock "$MODULE" "$RUNTIME_LOCK"
  echo "Created:"
  echo "  $RUNTIME_LOCK"
fi

# A passing qualification is immutable unless replacement is deliberate.
if [[ -f "$QUALIFICATION" ]]; then
  existing_model=""
  if existing_model="$(aw_qualification_model 2>/dev/null)"; then
    if [[ "$existing_model" == "$ADJUDICATION_MODEL" && "${FORCE_REQUALIFY:-0}" != "1" ]]; then
      echo
      echo "P0A is already qualified with $existing_model."
      echo "Preserving existing qualification: $QUALIFICATION"
      exit 0
    fi
    if [[ "$existing_model" != "$ADJUDICATION_MODEL" && "${FORCE_REQUALIFY:-0}" != "1" ]]; then
      aw_die "P0A is already qualified with $existing_model; set FORCE_REQUALIFY=1 to deliberately replace it with $ADJUDICATION_MODEL. The runtime lock should remain in place."
    fi
  fi
fi

# Archive prior qualification/evidence before a retry or deliberate requalification.
if [[ -e "$QUALIFICATION_ROOT" || -e "$QUALIFICATION" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  retry_root="$PRIVATE_ROOT/retries/$stamp"
  mkdir -p "$retry_root"
  [[ ! -e "$QUALIFICATION_ROOT" ]] || mv "$QUALIFICATION_ROOT" "$retry_root/"
  [[ ! -e "$QUALIFICATION" ]] || mv "$QUALIFICATION" "$retry_root/"
  echo
  echo "Archived prior P0A evidence to:"
  echo "  $retry_root"
fi

echo
echo "Running P0A synthetic Inspect qualification..."
echo "Model: $ADJUDICATION_MODEL"
echo "No real 120-case oracle labels are being generated."

set +e
"$AW" benchmark adjudication-inspect-qualify-live   "$MODULE"   "$RUNTIME_LOCK"   "$QUALIFICATION"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"   2>&1 | tee "$RUN_LOG"
qualify_rc=${PIPESTATUS[0]}
set -e

if [[ "$qualify_rc" -ne 0 ]]; then
  echo >&2
  echo "P0A qualification failed (exit $qualify_rc)." >&2
  echo "Captured output: $RUN_LOG" >&2

  correlation_id="$(
    grep -Eo 'correlation ID [0-9a-f]+' "$RUN_LOG"       | tail -n 1       | awk '{print $3}'
  )"
  if [[ -n "$correlation_id" ]]; then
    diagnostic="$HOME/.local/state/agent-workflow/diagnostics/unexpected/$correlation_id.json"
    if [[ -f "$diagnostic" ]]; then
      echo >&2
      echo "Unexpected-failure diagnostic summary:" >&2
      "$PYTHON" - "$diagnostic" <<'PY' >&2
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
exc = value.get("exception") or {}
print(f"  type: {exc.get('module')}.{exc.get('type')}")
print(f"  message: {exc.get('message')}")
for index, item in enumerate(exc.get("chain") or [], 1):
    print(
        f"  caused-by[{index}]: "
        f"{item.get('module')}.{item.get('type')}: {item.get('message')}"
    )
frames = value.get("traceback") or []
if frames:
    frame = frames[-1]
    print(
        "  final-frame: "
        f"{frame.get('path')}:{frame.get('line')} in {frame.get('function')}"
    )
print(f"  diagnostic: {sys.argv[1]}")
PY
    fi
  fi
  exit "$qualify_rc"
fi

echo
echo "Verifying newly created qualification..."
bash "$SCRIPT_DIR/verify-qualification.sh"

echo
echo "P0A qualification complete."
echo "Preserve both artifacts unchanged for P0B:"
echo "  $RUNTIME_LOCK"
echo "  $QUALIFICATION"
