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

Plugin version `0.3.1` declares `agent-workflow>=0.11.6,<0.12`; Agent-Workflow `0.11.6` is the minimum supported core for run-boundary semantic readiness. Agent-Workflow's compatibility lane pins this repository by commit so the plugin/core pair is reproducible rather than resolving a moving default branch.

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
agent-workflow benchmark run RUN_PLAN.json --execution-only
```

The smoke study keeps the canonical task, fixture, hidden evaluator, scoring contract, and direct executor identity fixed. Its control treatment is `raw-direct/v1`; its candidate treatment is `agent-workflow-full/v1`, which delegates each benchmark phase through Agent-Workflow using the same configured executor/model identity. Use `--agent-class` on `value-smoke-export` when the local Agent-Workflow runtime uses a different explicit agent class.

The run plan and experiment manifest record the stable internal arm slot separately from `treatment_id` and `runner_kind`. This preserves historical evidence schemas while allowing future structured-direct and ablation studies to reuse the paired harness.

Generic/future Codex benchmark exports now default to `gpt-6-luna`. The historical Round-2 `value-smoke-export` and BM3 `structured-value-smoke-export` helpers explicitly retain `gpt-5.6-luna` and its frozen local price catalog so rerunning those named historical studies does not silently change model cohorts. GPT-6 Luna local price estimates remain unset until a benchmark price catalog is explicitly defined.

Before a v3 plan is created, readiness verifies the Agent-Workflow treatment resolves to a comparable runtime: the mapped Agent-Workflow executor exists, provider family matches, the backend executable is the same direct Codex CLI in both arms, the model is permitted, reasoning-effort semantics are compatible, and the selected Agent-Workflow agent class permits that model. These checks are persisted in the run plan/experiment manifest.

The development installer and value-smoke runner use the same shared Agent-Workflow virtualenv and isolate Agent-Workflow runtime files under that venv:

```text
<venv>/.xdg/config
<venv>/.xdg/state
<venv>/.xdg/data
```

The installer writes a benchmark-owned, minimal venv-local Agent-Workflow config. It sets isolated `worktree_root`/`state_root`, enables only `agent-workflow-benchmark`, selects `semantic.provider = "typesafe"`, and sets `decision_policy.mode = "comparative"`. It does not mutate arbitrary user TOML. The smoke runner applies the XDG environment only to its own process, so the caller shell is automatically unchanged when the run exits.

The benchmark runtime is intentionally comparative: `typesafe-sdk==0.6.0`, `TYPESAFE_API_KEY`, and `agent-workflow-comparative-eval==0.1.0` are required in the shared venv. The comparative-eval package is a shared library, not an `agent_workflow.plugins` entry point.

### TypeSafe request/response audit

The value-smoke runner sets `AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG` to
`<smoke-root>/typesafe-api-audit.jsonl`. Agent-Workflow 0.11.6+ writes
redacted `agent-workflow/typesafe-api-call/v2` records there, including the
logical request, raw HTTP request/response bodies when exposed by TypeSafe SDK
0.6.0, normalized typed answers, model/version identity, hashes, and duration.
The evidence collector includes that JSONL file and records only aggregate
audit metadata in its manifest; the collector still refuses to archive if the
current `TYPESAFE_API_KEY` value appears anywhere in collected files.

For an authenticated end-to-end smoke run, the repository includes:

```bash
bash scripts/run-value-smoke.sh
```

The value smoke is intentionally **Codex-only**. It always uses the packaged `codex-subscription.json` executor profile; alternate provider profiles are not part of this smoke path.

Benchmark `0.3.1` requires Agent-Workflow `>=0.11.6,<0.12`. That core version automatically captures headless Codex JSONL telemetry so the Agent-Workflow arm can provide comparable input/cached/output/reasoning token evidence. After execution, the smoke validates `token_evidence_complete=true` for the selected attempt of both arms; an evidence failure preserves the run but prevents treating it as efficiency-qualified.

Useful environment overrides:

```bash
AGENT_CLASS=implementation bash scripts/run-value-smoke.sh
VALUE_SMOKE_ROOT=/tmp/aw-value-smoke-run bash scripts/run-value-smoke.sh
```

The helper exports the v3 smoke suite, creates the frozen fixture repository, verifies full-pipeline readiness before expensive execution, creates the paired plan, executes the paired treatments, then starts the live app and captures required visual evidence before machine scoring and consolidation. Human review remains a separate completion gate for composite/winner claims.

Git evidence now records committed, uncommitted, and untracked task changes. The canonical patch includes tracked changes relative to the benchmark base revision plus synthetic patches for untracked files, and `git-evidence.json` records both `base_revision` and `head_revision` so Agent-Workflow commits remain visible even when the worktree is clean.

After any completed or failed smoke run, preserve the raw evidence with:

```bash
python scripts/collect-value-smoke-evidence.py /tmp/agent-workflow-value-smoke.XXXXXX
```

If the smoke root is omitted, the collector chooses the newest `$TMPDIR/agent-workflow-value-smoke.*` directory. It packages the complete smoke root, the referenced coordinator run directory, and every arm evidence directory referenced by the run plan so `arm.json`, provider telemetry, Git evidence, and phase receipts remain self-contained. It records package/runtime identity without secret values, writes SHA-256 checksums, and refuses to archive if the current `TYPESAFE_API_KEY` value is found in collected files.

## BM3 structured-direct study

Benchmark 0.3 adds the diagnostic BM3 comparison:

```text
structured-direct/v1
vs
agent-workflow-full/v1
```

Both arms receive the structured `workflow_full` prompt profile; only the candidate runs through the real Agent-Workflow lifecycle. This isolates lifecycle/orchestration overhead from the structured-prompt treatment itself.

Run the full development study with:

```bash
bash scripts/run-bm3-structured.sh --help

bash scripts/run-bm3-structured.sh \
  --root /path/to/artifacts/bm3-$(date -u +%Y%m%dT%H%M%SZ) \
  --repetitions 1
```

The runner first performs a separate pre-treatment TypeSafe/Jev routing qualification over the three BM3 phase prompts, then runs readiness, planning, paired execution, machine scoring, descriptive reporting, granular timing capture, and self-contained evidence collection. The paired treatments themselves do not invoke semantic routing, preserving runtime comparability.

See [docs/BM3_STRUCTURED.md](docs/BM3_STRUCTURED.md) for the complete self-service workflow, manual command equivalent, evidence layout, troubleshooting, and interpretation rules.

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
