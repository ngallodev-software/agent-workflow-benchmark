#!/usr/bin/env bash
# Agent-directed Jev pilot environment. Source or let workflow scripts source it.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file instead: source scripts/agentic-jev/env.sh" >&2
  exit 2
fi

_AGENTIC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BENCH_REPO="${BENCH_REPO:-$(cd "$_AGENTIC_SCRIPT_DIR/../.." && pwd)}"
_STACK_ROOT="$(dirname "$BENCH_REPO")"

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$_STACK_ROOT/agent-workflow/.venv/bin/python" ]]; then
    PYTHON="$_STACK_ROOT/agent-workflow/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  else
    PYTHON=""
  fi
fi
export PYTHON

_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export AGENTIC_JEV_ROOT="${AGENTIC_JEV_ROOT:-$_DATA_HOME/agent-workflow/agentic-jev-pilot-v1}"
export AGENTIC_JEV_TASKS="${AGENTIC_JEV_TASKS:-$BENCH_REPO/src/agent_workflow_benchmark/assets/agentic-jev-pilot/tasks-v0.1.0-dev.1.json}"
export AGENTIC_JEV_RUNTIME_LOCK="${AGENTIC_JEV_RUNTIME_LOCK:-$AGENTIC_JEV_ROOT/runtime-lock.json}"
export AGENTIC_JEV_QUAL_ROOT="${AGENTIC_JEV_QUAL_ROOT:-$AGENTIC_JEV_ROOT/tool-qualification}"
export AGENTIC_JEV_QUALIFICATION="${AGENTIC_JEV_QUALIFICATION:-$AGENTIC_JEV_QUAL_ROOT/qualification.json}"
export AGENTIC_JEV_RUN="${AGENTIC_JEV_RUN:-$AGENTIC_JEV_ROOT/pilot-run}"

# Frozen coding-agent treatment identity for agentic-jev-pilot-v1.
# Reasoning effort is an Inspect generation option, not a provider model_arg.
export AGENTIC_JEV_MODEL="${AGENTIC_JEV_MODEL:-openai-api/codex-lb/gpt-6-luna}"
export AGENTIC_JEV_REASONING_EFFORT="${AGENTIC_JEV_REASONING_EFFORT:-high}"
export AGENTIC_JEV_MODEL_ARGS_JSON="${AGENTIC_JEV_MODEL_ARGS_JSON:-{\"responses_api\":true}}"
# Empty means TypeSafe selects its configured/default System One model.
export AGENTIC_JEV_JEV_MODEL="${AGENTIC_JEV_JEV_MODEL:-}"

# Same codex-lb provider defaults used by the adjudication lane. These are
# harmless when AGENTIC_JEV_MODEL selects another provider.
export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

mkdir -p "$AGENTIC_JEV_ROOT"
chmod 700 "$AGENTIC_JEV_ROOT"

unset _DATA_HOME _STACK_ROOT _AGENTIC_SCRIPT_DIR
