#!/usr/bin/env bash
set -Eeuo pipefail

AW_REPO="${AW_REPO:-/lump/apps/agent-workflow}"
BENCH_REPO="${BENCH_REPO:-/lump/apps/agent-workflow-benchmark}"
AW_VENV="${AW_VENV:-$AW_REPO/.venv}"
AW="$AW_VENV/bin/agent-workflow"
PYTHON="$AW_VENV/bin/python"

MODULE="$BENCH_REPO/modules/abc-adjudication/routing-semantic-v1.inspect.module.json"
PRIVATE_ROOT="${PRIVATE_ROOT:-$HOME/.local/share/agent-workflow/routing-semantic-v1-inspect}"
RUNTIME_LOCK="$PRIVATE_ROOT/runtime-lock.json"
QUALIFICATION="$PRIVATE_ROOT/qualification.json"
QUALIFICATION_ROOT="$PRIVATE_ROOT/inspect-qualification"
RUN_LOG="$PRIVATE_ROOT/p0a-qualify-last.log"

# Current routing-semantic-v1 adjudication cohort model.
# Do not infer this from ~/.codex/config.toml or previous interactive state.
# Override explicitly with MODEL_ID=... before P0A if intentionally starting a
# different adjudicator cohort; the resulting P0B run is bound to that model.
MODEL_ID="${MODEL_ID:-deepseek-flash}"
ADJUDICATION_MODEL="openai-api/codex-lb/$MODEL_ID"

export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"

# The localhost codex-lb endpoint does not require authentication. Inspect's
# generic openai-api provider nevertheless requires a non-empty
# <PROVIDER_NAME>_API_KEY value before it constructs the OpenAI client.
# This sentinel is not a credential; it exists only to satisfy that provider
# precondition and is covered by the sandbox secret-leakage guardrail.
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

mkdir -p "$PRIVATE_ROOT"
chmod 700 "$PRIVATE_ROOT"

fail() {
  echo "error: $*" >&2
  exit 1
}

[[ -x "$AW" ]] || fail "agent-workflow executable not found: $AW"
[[ -x "$PYTHON" ]] || fail "Python executable not found: $PYTHON"
[[ -f "$MODULE" ]] || fail "Inspect adjudication module not found: $MODULE"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v docker >/dev/null 2>&1 || fail "docker is required"

echo "Checking installed runtime versions..."
"$PYTHON" - <<'PY'
from importlib import metadata

required = {
    "agent-workflow-benchmark": "0.4.1",
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
  echo "Reusing frozen cohort runtime lock:"
  echo "  $RUNTIME_LOCK"
else
  echo "Creating frozen cohort runtime lock..."
  "$AW" benchmark adjudication-inspect-runtime-lock "$MODULE" "$RUNTIME_LOCK"
  echo "Created:"
  echo "  $RUNTIME_LOCK"
fi

# A failed live qualification can leave partial synthetic evidence. Archive it
# before retrying, but never regenerate or remove the cohort runtime lock.
if [[ -e "$QUALIFICATION_ROOT" || -e "$QUALIFICATION" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  retry_root="$PRIVATE_ROOT/retries/$stamp"
  mkdir -p "$retry_root"
  if [[ -e "$QUALIFICATION_ROOT" ]]; then
    mv "$QUALIFICATION_ROOT" "$retry_root/"
  fi
  if [[ -e "$QUALIFICATION" ]]; then
    mv "$QUALIFICATION" "$retry_root/"
  fi
  echo
  echo "Archived prior P0A attempt to:"
  echo "  $retry_root"
fi

echo
echo "Running P0A synthetic Inspect qualification..."
echo "Model: $MODEL_ID"
echo "No real 120-case oracle labels are being generated."

set +e
"$AW" benchmark adjudication-inspect-qualify-live   "$MODULE"   "$RUNTIME_LOCK"   "$QUALIFICATION"   --model "$ADJUDICATION_MODEL"   --model-arg responses_api=true   2>&1 | tee "$RUN_LOG"
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
chain = exc.get("chain") or []
for index, item in enumerate(chain, 1):
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
echo "Checking qualification result..."
"$PYTHON" - "$QUALIFICATION" "$MODEL_ID" <<'PY'
import json
import sys

path, expected_model = sys.argv[1], sys.argv[2]
value = json.load(open(path, encoding="utf-8"))

print("P0A qualification gates:")
for gate, evidence in value.get("gates", {}).items():
    print(f"  {gate}: {evidence.get('status')}")

if value.get("qualified") is not True:
    raise SystemExit("P0A DID NOT QUALIFY. P0B remains blocked.")

failed = [
    gate
    for gate, evidence in value.get("gates", {}).items()
    if evidence.get("status") != "pass"
]
if failed:
    raise SystemExit(
        "P0A DID NOT QUALIFY. Failed gates: " + ", ".join(failed)
    )

recorded_model = (
    value.get("gates", {})
    .get("IA-2", {})
    .get("evidence", {})
    .get("model")
)
expected_qualified_model = f"openai-api/codex-lb/{expected_model}"
if recorded_model != expected_qualified_model:
    raise SystemExit(
        f"qualification recorded model {recorded_model!r}; "
        f"expected {expected_qualified_model!r}"
    )

print()
print(f"P0A QUALIFIED with {expected_model}")
print(path)
PY

echo
echo "Qualification complete."
echo "Keep both artifacts unchanged for P0B:"
echo "  $RUNTIME_LOCK"
echo "  $QUALIFICATION"
