# BM3 — Structured Direct vs Agent-Workflow Full

## Question

BM3 asks a narrower question than Round 2:

> What time, token, quality, and evidence differences remain when both arms receive the same structured workflow discipline, but only one arm executes through the real Agent-Workflow lifecycle?

Treatments:

- `structured-direct/v1` — the structured workflow profile runs directly through Codex CLI;
- `agent-workflow-full/v1` — the same structured profile runs through Agent-Workflow Agent Runs.

The study is Codex-only and uses the same provider/model/executor cohort for both arms.

## Install/update the complete stack

From the Agent-Workflow repository:

```bash
export AGENT_WORKFLOW_VENV=/lump/apps/agent-workflow/.venv
export TYPESAFE_API_KEY='...'

bash scripts/build-install-all.sh --venv "$AGENT_WORKFLOW_VENV"
```

A normal full build now performs a safe fast-forward pull of all stack repositories first:

- Agent-Workflow contract library;
- comparative-eval;
- SpecGen;
- benchmark plugin;
- Agent-Workflow.

It refuses dirty/diverged/detached/untracked-upstream states rather than resetting or switching branches.

Useful alternatives:

```bash
# Update repositories only.
bash scripts/build-install-all.sh --pull-only

# Rebuild exactly the checked-out source without network mutation.
bash scripts/build-install-all.sh --no-pull --venv "$AGENT_WORKFLOW_VENV"

# Verify the installed stack without pulling or rebuilding.
bash scripts/build-install-all.sh --verify-only --venv "$AGENT_WORKFLOW_VENV"
```

## Preflight

```bash
source /lump/apps/agent-workflow/scripts/dev-env.sh on "$AGENT_WORKFLOW_VENV"

agent-workflow --version
agent-workflow doctor
agent-workflow decision check
agent-workflow plugins list
agent-workflow benchmark --help
codex login status
```

BM3 requires:

- Agent-Workflow 0.11.6;
- agent-workflow-benchmark 0.3.0;
- TypeSafe SDK 0.6.0;
- comparative decision mode;
- compatible comparative-eval library;
- `TYPESAFE_API_KEY`;
- authenticated Codex subscription session.

## One-command BM3 development run

From the benchmark repository:

```bash
cd /lump/apps/agent-workflow-benchmark

bash scripts/run-bm3-structured.sh \
  --root /lump/apps/agent-workflow-benchmark/artifacts/bm3-$(date -u +%Y%m%dT%H%M%SZ) \
  --repetitions 1
```

Run:

```bash
bash scripts/run-bm3-structured.sh --help
```

for the live option contract.

The runner performs:

1. version and semantic-runtime preflight;
2. structured BM3 suite export;
3. frozen fixture creation;
4. execution-only readiness checks;
5. paired run planning;
6. paired execution;
7. machine scoring;
8. descriptive report generation;
9. TypeSafe audit/timing summary generation;
10. self-contained evidence collection.

## Manual equivalent

The one-command runner is preferred, but every step can be executed separately.

```bash
ROOT=/tmp/agent-workflow-bm3-manual
mkdir -p "$ROOT"

agent-workflow benchmark structured-value-smoke-export "$ROOT/suite"
agent-workflow benchmark fixture-create \
  "$ROOT/suite/benchmark-spec.json" \
  "$ROOT/fixture"

agent-workflow benchmark readiness \
  "$ROOT/suite/benchmark-spec.json" \
  --executor "$ROOT/suite/executors/codex-subscription.json" \
  --policy "$ROOT/suite/policies/development.json" \
  --execution-only

agent-workflow --json benchmark plan \
  "$ROOT/suite/benchmark-spec.json" \
  --repo "$ROOT/fixture" \
  --base-ref HEAD \
  --executor "$ROOT/suite/executors/codex-subscription.json" \
  --policy "$ROOT/suite/policies/development.json" \
  --repetitions 1 > "$ROOT/plan.json"
```

Read `run_plan` from `plan.json`, then:

```bash
agent-workflow benchmark run RUN_PLAN.json --execution-only
agent-workflow benchmark score RUN_PLAN.json
agent-workflow benchmark report RUN_PLAN.json
```

## Timing evidence

BM3 records both benchmark-level and Agent-Workflow-internal timing.

### Per benchmark phase

Every `phase.json` includes:

- `phase_wall_seconds`;
- `active_process_seconds`;
- provider timing/usage;
- `timing_breakdown`.

Direct phases include:

- executor-active time;
- benchmark postprocessing time;
- derived host overhead.

Agent-Workflow phases include:

- delegate-call time;
- terminal-wait time;
- benchmark evidence-collection time;
- executor-active time;
- derived host overhead;
- copied Agent-Workflow terminal-pipeline timing.

### Agent-Workflow terminal pipeline

Each Agent Run may contain sealed `terminal-timing.json` with host-side section timings for:

- completion collection;
- assignment close;
- task-result collection;
- post-policy collection;
- patch capture;
- provider-evidence normalization;
- budget/policy evaluation;
- provenance update;
- final-status write;
- execution-evidence generation;
- pre-seal terminal total.

These sections occur after executor exit and therefore distinguish deterministic host work from the coding-model process duration.

## TypeSafe/Jev audit

The runner sets:

```text
AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG=<BM3 root>/typesafe-api-audit.jsonl
```

The private JSONL contains redacted `agent-workflow/typesafe-api-call/v2` records with:

- projected state;
- exact Choice/Noul/Score question definitions;
- requested/resolved model;
- request hash;
- SDK version;
- raw HTTP request/response when exposed by the SDK;
- normalized results;
- duration/status/error.

Inspect privately:

```bash
jq . "$ROOT/typesafe-api-audit.jsonl" | less
```

Do not publish raw request/response bodies. Use counts, duration, primitive coverage, disagreement/calibration metrics, and hashes in public summaries.

## Evidence archive

The runner automatically calls:

```bash
python scripts/collect-value-smoke-evidence.py "$ROOT" \
  --output "$ROOT-evidence.tar.gz"
```

Benchmark 0.2.9+ follows every arm `stage_dir` in the run plan, so the archive includes coordinator evidence and the actual treatment-arm evidence roots.

The collector refuses to create the archive if the current `TYPESAFE_API_KEY` byte value is present in collected files.

## Machine scoring and interpretation

BM3 deliberately scores after execution even when visual/human evidence is absent.

That allows development comparison of observed machine quality against:

- wall time;
- provider tokens;
- executor-active time;
- host overhead;
- TypeSafe decision time.

Missing visual/human evidence may make a pair ineligible for a composite/winner claim. The observed machine score is still diagnostically useful.

One development repetition remains descriptive. Increase repetitions only after the harness and evidence have been inspected.

## Diagnosing overhead

Start with four questions:

1. **Did executor-active time increase?**  
   If yes, the structured Agent-Workflow context/prompt is causing the coding model itself to work longer.

2. **Did host overhead increase materially?**  
   Inspect delegate, terminal-pipeline, and evidence-collection timing before changing model behavior.

3. **Did tokens increase without quality improvement?**  
   Inspect prompt/evidence duplication and context selection.

4. **Is the coding model making bounded decisions?**  
   Compare those steps with the candidate Jev seams documented in Agent-Workflow's `docs/BM3_TYPESAFE_JEV_OPTIMIZATION_AUDIT.md`.

## Troubleshooting

### Missing TypeSafe key

```text
BM3 requires TYPESAFE_API_KEY
```

Load the key into the shell before running. Do not write it to TOML, scripts, benchmark assets, or evidence.

### Comparative runtime not ready

Run:

```bash
agent-workflow decision check
agent-workflow doctor
```

Verify TypeSafe SDK, the key, and comparative-eval compatibility.

### Codex authentication failure

Run:

```bash
codex login status
agent-workflow benchmark auth-check \
  "$ROOT/suite/executors/codex-subscription.json"
```

The study is subscription-session only.

### Token evidence incomplete

Do not substitute zero. Preserve the run and inspect the arm's provider evidence and `execution-metrics.json`.

### Scoring is ineligible

Inspect the score guardrails. Missing visual evidence is expected for the execution-first BM3 development path; distinguish `observed machine score` from an eligible composite/winner claim.

### Dirty stack repository during build

Commit/stash the work or intentionally use:

```bash
bash scripts/build-install-all.sh --no-pull ...
```

`--allow-dirty-pull` exists for an explicit operator override, but it never resets/stashes and `git pull --ff-only` may still refuse the update.

## After BM3

Do not immediately replace workflow decisions with Jev.

Use the timing, score, request/response audit, and comparative decision receipts to identify bounded seams where:

- the output taxonomy is finite;
- the projected state is sufficient;
- uncertainty is explicit;
- TypeSafe is reliable/calibratable;
- deterministic policy can reject/fallback;
- measured LLM time/context is meaningfully reduced.

Then add those seams first in comparative/shadow mode.
