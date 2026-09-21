# Agent-Workflow Benchmark Plugin

`agent-workflow-benchmark` is the optional comparative-benchmark capability extracted from Agent-Workflow core. It owns benchmark-specific execution, suites, schemas, scoring/reporting, visual capture support, target manifests, and the historical matched-cohort benchmark compatibility commands.

Agent-Workflow core continues to own generic evaluation, review/acceptance, lifecycle, and plugin authority.

## Install

Install this package into the same Python environment as Agent-Workflow:

```bash
python -m pip install agent-workflow-benchmark
```

For visual benchmark capture:

```bash
python -m pip install 'agent-workflow-benchmark[visual]'
```

Enable the plugin in Agent-Workflow configuration:

```toml
[plugins]
enabled = ["agent-workflow-benchmark"]
```

The `benchmark` command is contributed through the normal `agent_workflow.plugins` entry-point API; Agent-Workflow does not hardcode it. Confirm discovery with:

```bash
agent-workflow --help
agent-workflow benchmark --help
agent-workflow plugins list
agent-workflow commands --format markdown
```

`agent-workflow --no-plugins --help` intentionally shows only the core recovery surface.

## Core compatibility

Plugin version `0.2.0` declares `agent-workflow>=0.11.0,<0.12`; Agent-Workflow `0.11.2` is inside that supported range. Agent-Workflow's compatibility lane pins this repository by commit so the plugin/core pair is reproducible rather than resolving a moving default branch.

## Main workflow

A typical development run is:

```bash
agent-workflow benchmark suite-export /tmp/priority-picker-v2 --benchmark-id priority-picker-v2
agent-workflow benchmark validate /tmp/priority-picker-v2/benchmark-spec.json
agent-workflow benchmark auth-check /tmp/priority-picker-v2/executors/codex-subscription.json
agent-workflow benchmark readiness /tmp/priority-picker-v2/benchmark-spec.json \
  --executor /tmp/priority-picker-v2/executors/codex-subscription.json \
  --policy /tmp/priority-picker-v2/policies/development.json
agent-workflow benchmark plan /tmp/priority-picker-v2/benchmark-spec.json \
  --repo /path/to/target --base-ref HEAD \
  --executor /tmp/priority-picker-v2/executors/codex-subscription.json \
  --policy /tmp/priority-picker-v2/policies/development.json
agent-workflow benchmark run RUN_PLAN.json
```

Other lifecycle commands include `resume`, `status`, `live-start`, `live-stop`, `visual-capture`, `score`, `review`, `consolidate`, `report`, `verify`, and `cleanup`. Use `agent-workflow benchmark --help` for the live command tree.

## Agent-Workflow value smoke study

Version 0.2 adds benchmark-spec/v3 treatment identity and a runner boundary that can compare a direct coding-agent execution with the real Agent-Workflow Agent Run lifecycle. Historical v1/v2 suites keep their original semantics: their `workflow_full` arm is the structured direct-execution profile, not an Agent-Workflow runtime invocation.

Create the first value smoke suite from the existing priority-picker-v2 fixture/evaluator:

```bash
agent-workflow benchmark value-smoke-export /tmp/aw-value-smoke
agent-workflow benchmark validate /tmp/aw-value-smoke/benchmark-spec.json
agent-workflow benchmark plan /tmp/aw-value-smoke/benchmark-spec.json \
  --repo /path/to/target \
  --base-ref HEAD \
  --executor /tmp/aw-value-smoke/executors/codex-subscription.json \
  --policy /tmp/aw-value-smoke/policies/development.json
agent-workflow benchmark run RUN_PLAN.json
```

The smoke study keeps the canonical task, fixture, hidden evaluator, scoring contract, and direct executor identity fixed. Its control treatment is `raw-direct/v1`; its candidate treatment is `agent-workflow-full/v1`, which delegates each benchmark phase through Agent-Workflow using the same configured executor/model identity. Use `--agent-class` on `value-smoke-export` when the local Agent-Workflow runtime uses a different explicit agent class.

The run plan and experiment manifest record the stable internal arm slot separately from `treatment_id` and `runner_kind`. This preserves historical evidence schemas while allowing future structured-direct and ablation studies to reuse the paired harness.

## Legacy command migration

The former Agent-Workflow core commands are preserved under explicit compatibility names:

```text
agent-workflow eval validate-benchmark  -> agent-workflow benchmark legacy-validate
agent-workflow eval benchmark-report    -> agent-workflow benchmark legacy-report
```

Generated benchmark reports now reproduce the plugin-owned command paths. Historical schema IDs remain unchanged because they identify evidence semantics, not Python package ownership.

## CLI reference

The CLI is generated from the plugin parser at runtime. Do not maintain a separate static command list or man page; use:

```bash
agent-workflow benchmark --help
agent-workflow commands --format markdown
agent-workflow completion bash
```

so documentation/completion stays aligned with the installed plugin version.
