#!/usr/bin/env bash
# Sourceable environment for routing-semantic-v1 P1/P2/P3 execution.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file instead: source scripts/decision-study/env.sh" >&2
  exit 2
fi

_DECISION_STUDY_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BENCH_REPO="${BENCH_REPO:-$(cd "$_DECISION_STUDY_SCRIPT_DIR/../.." && pwd)}"
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
export DECISION_STUDY_ROOT="${DECISION_STUDY_ROOT:-$_DATA_HOME/agent-workflow/routing-semantic-v1-decision-study}"

if [[ -n "$COMP_REPO" ]]; then
  export SOURCE_CORPUS="${SOURCE_CORPUS:-$COMP_REPO/src/agent_workflow_comparative_eval/resources/studies/routing-semantic-v1.corpus.json}"
else
  export SOURCE_CORPUS="${SOURCE_CORPUS:-}"
fi

export FROZEN_ORACLE="${FROZEN_ORACLE:-$_DATA_HOME/agent-workflow/routing-semantic-v1-inspect/oracle-run/oracle.json}"

export P1_SAMPLE_SIZE="${P1_SAMPLE_SIZE:-8}"
export P1_ROOT="${P1_ROOT:-$DECISION_STUDY_ROOT/p1-smoke}"
export P1_CORPUS="${P1_CORPUS:-$P1_ROOT/corpus-smoke.json}"
export P1_SELECTION="${P1_SELECTION:-$P1_ROOT/selection.json}"
export P1_RUN="${P1_RUN:-$P1_ROOT/run}"
export P1_VERIFICATION="${P1_VERIFICATION:-$P1_ROOT/verification.json}"

export P2_ROOT="${P2_ROOT:-$DECISION_STUDY_ROOT/p2-full}"
export P2_RUN="${P2_RUN:-$P2_ROOT/run}"

export P3_ROOT="${P3_ROOT:-$DECISION_STUDY_ROOT/p3-publication}"
export P3_PUBLIC="${P3_PUBLIC:-$P3_ROOT/public}"

mkdir -p "$DECISION_STUDY_ROOT"
chmod 700 "$DECISION_STUDY_ROOT"

unset _DATA_HOME _STACK_ROOT _DECISION_STUDY_SCRIPT_DIR
