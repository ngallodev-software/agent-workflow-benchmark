#!/usr/bin/env bash
# Source this file to expose adjudication study paths in the current shell.
# Executable workflow scripts source it automatically.
#
# Resolution policy:
# - BENCH_REPO is derived from this script's own location unless explicitly set.
# - AW prefers an explicit value, then the installed agent-workflow on PATH,
#   then the conventional sibling-repo shared virtualenv as a fallback.
# - PYTHON prefers an explicit value, then the Python beside AW, then python3.
# - COMP_REPO prefers an explicit value, then a sibling comparative-eval checkout.
# - PRIVATE_ROOT defaults to XDG_DATA_HOME (or ~/.local/share), never a repo path.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file instead: source scripts/adjudication/env.sh" >&2
  exit 2
fi

_ADJUDICATION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BENCH_REPO="${BENCH_REPO:-$(cd "$_ADJUDICATION_SCRIPT_DIR/../.." && pwd)}"
_STACK_ROOT="$(dirname "$BENCH_REPO")"

if [[ -z "${AW:-}" ]]; then
  if command -v agent-workflow >/dev/null 2>&1; then
    AW="$(command -v agent-workflow)"
  elif [[ -x "$_STACK_ROOT/agent-workflow/.venv/bin/agent-workflow" ]]; then
    AW="$_STACK_ROOT/agent-workflow/.venv/bin/agent-workflow"
  else
    AW=""
  fi
fi
export AW

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -n "$AW" && -x "$(dirname "$AW")/python" ]]; then
    PYTHON="$(dirname "$AW")/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  else
    PYTHON=""
  fi
fi
export PYTHON

if [[ -z "${COMP_REPO:-}" && -d "$_STACK_ROOT/agent-workflow-comparative-eval" ]]; then
  COMP_REPO="$(cd "$_STACK_ROOT/agent-workflow-comparative-eval" && pwd)"
fi
export COMP_REPO="${COMP_REPO:-}"

_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export PRIVATE_ROOT="${PRIVATE_ROOT:-$_DATA_HOME/agent-workflow/routing-semantic-v1-inspect}"

export MODULE="${MODULE:-$BENCH_REPO/modules/abc-adjudication/routing-semantic-v1.inspect.module.json}"
export RUNTIME_LOCK="${RUNTIME_LOCK:-$PRIVATE_ROOT/runtime-lock.json}"
export QUALIFICATION="${QUALIFICATION:-$PRIVATE_ROOT/qualification.json}"

if [[ -n "$COMP_REPO" ]]; then
  export ORACLE_VIEW="${ORACLE_VIEW:-$COMP_REPO/docs/studies/artifacts/routing-semantic-v1/oracle-authoring-view.json}"
  export ORACLE_PROTOCOL="${ORACLE_PROTOCOL:-$COMP_REPO/docs/studies/routing-semantic-v1-oracle-protocol.md}"
  export CORPUS="${CORPUS:-$COMP_REPO/src/agent_workflow_comparative_eval/resources/studies/routing-semantic-v1.corpus.json}"
else
  export ORACLE_VIEW="${ORACLE_VIEW:-}"
  export ORACLE_PROTOCOL="${ORACLE_PROTOCOL:-}"
  export CORPUS="${CORPUS:-}"
fi

export ORACLE_RUN="${ORACLE_RUN:-$PRIVATE_ROOT/oracle-run}"
export DISPUTE_VIEW="${DISPUTE_VIEW:-$ORACLE_RUN/oracle-disputes-for-c.json}"

export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
# codex-lb itself does not require this credential. Inspect's generic
# openai-api provider requires a non-empty provider API-key value.
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

mkdir -p "$PRIVATE_ROOT"
chmod 700 "$PRIVATE_ROOT"

unset _DATA_HOME _STACK_ROOT _ADJUDICATION_SCRIPT_DIR
