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

For a source checkout used alongside an Agent-Workflow wheel, use the repository
installer so the plugin is built and installed into the **same shared virtualenv**
that owns the `agent-workflow` launcher:

```bash
bash scripts/build-install.sh
```

The script discovers that virtualenv from the resolved `agent-workflow` launcher,
or accepts an explicit path:

```bash
bash scripts/build-install.sh --venv /path/to/shared-agent-workflow-venv
```

It performs a clean wheel build, uninstalls the previous benchmark distribution,
removes only benchmark-owned stale package artifacts, installs the new wheel with
`--no-deps` so Agent-Workflow itself is not replaced, then verifies:

- Agent-Workflow and the benchmark distribution resolve from the same virtualenv;
- the installed benchmark version matches this checkout;
- the source, wheel, installed package, and plugin descriptor expose the same schema set and digests;
- exactly one `agent_workflow.plugins` benchmark entry point exists;
- the benchmark distribution owns no standalone console script;
- no stale `benchmark-*.schema.json` files remain in Agent-Workflow's XDG host-data schema directory;
- no stale benchmark schemas remain under the shared virtualenv's Agent-Workflow data files;
- no obsolete `agent-workflow-benchmark` launcher shadows plugin discovery;
- the active `agent-workflow` command resolves to the selected shared virtualenv.

To audit an existing installation without rebuilding it:

```bash
bash scripts/build-install.sh --verify-only
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

Plugin version `0.2.2` declares `agent-workflow>=0.11.0,<0.12`; Agent-Workflow `0.11.2` is inside that supported range. Agent-Workflow's compatibility lane pins this repository by commit so the plugin/core pair is reproducible rather than resolving a moving default branch.

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
agent-workflow benchmark run RUN_PLAN.json --execution-only
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

Before a v3 plan is created, readiness verifies the Agent-Workflow treatment resolves to a comparable runtime: the mapped Agent-Workflow executor exists, provider family matches, the backend executable is either the direct Codex CLI or Agent-Workflow's owned `agent-workflow-codex` wrapper, the model is permitted, reasoning-effort semantics are compatible, and the selected Agent-Workflow agent class permits that model. These checks are persisted in the run plan/experiment manifest.

For an authenticated end-to-end smoke run, the repository includes:

```bash
bash scripts/run-value-smoke.sh
```

The value smoke is intentionally **Codex-only**. It always uses the packaged `codex-subscription.json` executor profile; alternate provider profiles are not part of this smoke path.

Useful environment overrides:

```bash
AGENT_CLASS=implementation bash scripts/run-value-smoke.sh
VALUE_SMOKE_ROOT=/tmp/aw-value-smoke-run bash scripts/run-value-smoke.sh
```

The helper exports the v3 smoke suite, creates the frozen fixture repository, runs execution-only readiness, creates the paired plan, and executes the paired treatments without entering visual capture or human-review finalization. Visual runtime attestation remains required for normal benchmark runs. The smoke stops before planning if runtime comparability or Codex subscription authentication is not verified.

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
