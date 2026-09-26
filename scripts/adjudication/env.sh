#!/usr/bin/env bash
# Source this file to expose the adjudication study paths in the current shell.
# Executable workflow scripts source it automatically.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file instead: source scripts/adjudication/env.sh" >&2
  exit 2
fi

_ADJUDICATION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BENCH_REPO="${BENCH_REPO:-$(cd "$_ADJUDICATION_SCRIPT_DIR/../.." && pwd)}"
_STACK_ROOT="$(dirname "$BENCH_REPO")"

export AW_REPO="${AW_REPO:-$_STACK_ROOT/agent-workflow}"
export COMP_REPO="${COMP_REPO:-$_STACK_ROOT/agent-workflow-comparative-eval}"
export AW_VENV="${AW_VENV:-$AW_REPO/.venv}"
export AW="${AW:-$AW_VENV/bin/agent-workflow}"
export PYTHON="${PYTHON:-$AW_VENV/bin/python}"

export PRIVATE_ROOT="${PRIVATE_ROOT:-$HOME/.local/share/agent-workflow/routing-semantic-v1-inspect}"
export MODULE="${MODULE:-$BENCH_REPO/modules/abc-adjudication/routing-semantic-v1.inspect.module.json}"
export RUNTIME_LOCK="${RUNTIME_LOCK:-$PRIVATE_ROOT/runtime-lock.json}"
export QUALIFICATION="${QUALIFICATION:-$PRIVATE_ROOT/qualification.json}"

export ORACLE_VIEW="${ORACLE_VIEW:-$COMP_REPO/docs/studies/artifacts/routing-semantic-v1/oracle-authoring-view.json}"
export ORACLE_PROTOCOL="${ORACLE_PROTOCOL:-$COMP_REPO/docs/studies/routing-semantic-v1-oracle-protocol.md}"
export CORPUS="${CORPUS:-$COMP_REPO/src/agent_workflow_comparative_eval/resources/studies/routing-semantic-v1.corpus.json}"

export ORACLE_RUN="${ORACLE_RUN:-$PRIVATE_ROOT/oracle-run}"
export DISPUTE_VIEW="${DISPUTE_VIEW:-$ORACLE_RUN/oracle-disputes-for-c.json}"

export CODEX_LB_BASE_URL="${CODEX_LB_BASE_URL:-http://127.0.0.1:2455/v1}"
# codex-lb itself does not require this credential. Inspect's generic
# openai-api provider requires a non-empty provider API-key value.
export CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"

mkdir -p "$PRIVATE_ROOT"
chmod 700 "$PRIVATE_ROOT"

unset _STACK_ROOT _ADJUDICATION_SCRIPT_DIR
