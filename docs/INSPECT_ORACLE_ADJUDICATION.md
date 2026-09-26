# Inspect Oracle Adjudication — Debian Operator Guide

This is the preferred execution path for `routing-semantic-v1` after benchmark 0.4.1.

It replaces the direct-Docker runner as the preferred backend only after the synthetic P0A qualification suite passes. The direct-Docker runner remains the rollback/reference implementation.

## Invariants

Do not change these for the current study:

- study: `routing-semantic-v1`
- dataset: `routing-semantic-corpus-v1.0.0`
- corpus SHA-256: `e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280`
- A/B view SHA-256: `a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a`
- oracle protocol: `routing-semantic-oracle-v1.0.0`

The real 120-case authoring view is not used during P0A qualification.

## Version policy

Python runtime dependencies are pinned:

- `inspect-ai==0.3.268`
- `inspect-swe==0.2.70`

Codex CLI is intentionally not repository-pinned.

At cohort start the runtime-lock command resolves the current `@openai/codex` npm `latest` metadata to an exact version, asks Inspect SWE to cache that exact version, records it, and freezes that identity for the cohort. This avoids accidentally selecting some other previously cached Codex build.

A, B, and any required C pass must all use the same runtime lock.

Do not re-run the runtime-lock command after real A/B adjudication begins.

## 1. Update and install the benchmark

From the benchmark checkout:

~~~bash
git pull --ff-only

/path/to/shared-agent-workflow-venv/bin/python -m pip install -U   '.[inspect]'
~~~

Or rebuild/install through the normal repository installer, then ensure the Inspect extra exists in the same shared virtualenv.

Verify:

~~~bash
/path/to/shared-agent-workflow-venv/bin/python - <<'PY'
from importlib import metadata

print("benchmark", metadata.version("agent-workflow-benchmark"))
print("inspect-ai", metadata.version("inspect-ai"))
print("inspect-swe", metadata.version("inspect-swe"))
PY
~~~

Expected benchmark version for this implementation: `0.4.1`.

## 2. Configure the host-side codex-lb provider

The current `routing-semantic-v1` adjudication cohort uses the local `codex-lb`
OpenAI-compatible endpoint. The repository launcher defaults to
**`deepseek-flash`** and permits an explicit `MODEL_ID=...` override only when
intentionally starting a different adjudicator cohort. Do not derive the model
from `~/.codex/config.toml`, a prior interactive session, or a provider default.

Set the provider base URL **on the Debian host**, not in the adjudicator sandbox:

~~~bash
export CODEX_LB_BASE_URL='http://127.0.0.1:2455/v1'
export ADJUDICATION_MODEL='openai-api/codex-lb/deepseek-flash'
export ADJUDICATION_MODEL_ARGS=(--model-arg responses_api=true)
~~~

Local `codex-lb` access does not require authentication. Inspect's generic
`openai-api` provider nevertheless requires a non-empty
`<PROVIDER_NAME>_API_KEY` value before constructing its OpenAI-compatible
client. For this localhost-only path, use a non-secret sentinel:

~~~bash
export CODEX_LB_API_KEY='inspect-placeholder'
~~~

That value is not a `codex-lb` credential. It only satisfies Inspect's provider
precondition and is included in the P0A host-secret leakage probe so the
qualification still verifies that provider-side values do not enter the
sandbox.

Do not export `TYPESAFE_API_KEY` into an adjudicator container. P0A and P0B
oracle production do not need TypeSafe/Jev credentials.

The Inspect sandbox has `network_mode: none`. Codex model traffic reaches the
host Inspect provider through Inspect's sandbox-agent bridge.

The sandbox also drops all Linux capabilities by default and restores only
`CHOWN` and `FOWNER`. Inspect SWE's pinned Codex package installer runs
`tar -xzf` as root, which restores package ownership, and then applies
`chmod +x` to the entrypoint. Those two capabilities are the minimum required
for that install step; the live IA-3 guardrail reproduces the package extraction
pattern to verify the hardened profile remains compatible.

## 2A. Preferred P0A launcher

The repository-owned P0A entry point is:

~~~bash
cd /lump/apps/agent-workflow-benchmark
bash scripts/adjudication/p0a-qualify.sh
~~~

Run it with `bash`; do **not** source it into an interactive SSH shell.

The launcher:

- verifies benchmark/Inspect versions;
- verifies that the selected `MODEL_ID` is present in the live `codex-lb /models` list;
- defaults to `deepseek-flash` and passes the fully-qualified model explicitly;
- creates the cohort runtime lock once and reuses it on retries;
- archives partial synthetic qualification evidence from failed attempts without
  replacing the runtime lock;
- prints a bounded summary of Agent-Workflow unexpected-failure diagnostics when
  Inspect raises outside the normal `WorkflowError` path;
- refuses to report success unless all IA-1 through IA-8 gates pass and IA-2
  records the expected explicit model.

The P0A qualification manifest records the exact Inspect model under
`IA-2.evidence.model`. Real A/B/C commands must use that same fully-qualified
model. The benchmark rejects a P0B run whose requested model differs from the
qualified model, so changing the adjudicator model requires a new P0A
qualification for that cohort.

For a fully scripted execution, use the organized adjudication suite:

~~~bash
bash scripts/adjudication/verify-qualification.sh
bash scripts/adjudication/p0b-run-ab.sh
~~~

Or run the complete qualification-to-oracle workflow:

~~~bash
bash scripts/adjudication/run-all.sh
~~~

The staged scripts remain available for validation, dispute construction, C,
freeze, and final oracle validation. See `scripts/adjudication/README.md`.
The manual commands below are retained as the transparent protocol reference.

The remaining sections document the same procedure manually and are retained for
auditability and diagnosis.

IA-5's direct-Docker wrapper parity fixture uses host bind mounts for synthetic
input/output evidence. It runs the wrapper as the invoking host UID:GID rather
than as container root. This keeps restrictive host file modes intact and works
with rootless/user-namespaced Docker daemons without granting broader write
permissions to the evidence directory.

## 3. Define paths

Example:

~~~bash
export AW_VENV=/path/to/shared-agent-workflow-venv
export AW="$AW_VENV/bin/agent-workflow"

export BENCH_REPO=/path/to/agent-workflow-benchmark
export COMP_REPO=/path/to/agent-workflow-comparative-eval

export MODULE="$BENCH_REPO/modules/abc-adjudication/routing-semantic-v1.inspect.module.json"

export PRIVATE_ROOT=/private/path/routing-semantic-v1-inspect
mkdir -p "$PRIVATE_ROOT"

export RUNTIME_LOCK="$PRIVATE_ROOT/runtime-lock.json"
export QUALIFICATION="$PRIVATE_ROOT/qualification.json"

export ORACLE_VIEW="$COMP_REPO/docs/studies/artifacts/routing-semantic-v1/oracle-authoring-view.json"
export ORACLE_PROTOCOL="$COMP_REPO/docs/studies/routing-semantic-v1-oracle-protocol.md"
export CORPUS="$COMP_REPO/src/agent_workflow_comparative_eval/resources/studies/routing-semantic-v1.corpus.json"
~~~

The private root must not be committed.

## 4. Validate the module

~~~bash
"$AW" benchmark adjudication-module-validate "$MODULE"
~~~

The module must report:

- runtime kind `inspect-ai`;
- host-only provider credentials;
- sandbox network `none`;
- no repository mount;
- no Docker socket;
- no cross-adjudicator visibility.

## 5. Resolve current Codex and freeze the cohort runtime

Run this once:

~~~bash
"$AW" benchmark adjudication-inspect-runtime-lock   "$MODULE"   "$RUNTIME_LOCK"
~~~

This resolves current Codex `latest` through Inspect SWE and records the exact result.

Inspect it:

~~~bash
python -m json.tool "$RUNTIME_LOCK"
~~~

The important fields are:

~~~text
backend = inspect-ai
inspect_ai_version = 0.3.268
inspect_swe_version = 0.2.70
codex_cli.policy = latest-at-cohort-start
codex_cli.requested = latest
codex_cli.resolved = <exact version resolved today>
frozen_for_cohort = true
~~~

Do not regenerate this file for B or C.

## 6. Run P0A synthetic qualification

This command never sends the real 120-case authoring view to an agent.

~~~bash
"$AW" benchmark adjudication-inspect-qualify-live   "$MODULE"   "$RUNTIME_LOCK"   "$QUALIFICATION"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"
~~~

The qualification suite exercises:

- IA-1 runtime/dependency identity;
- IA-2 host provider bridge using synthetic cases;
- IA-3 sandbox leakage guardrail probe;
- IA-4 shared prompt/input identity parity;
- IA-5 direct-Docker wrapper vs Inspect adapter contract parity;
- IA-6 independent synthetic A/B execution;
- IA-7 synthetic dispute-only C execution;
- IA-8 complete synthetic freeze/rollback compatibility.

The guardrail probe compares hashes of any host secret-like environment values against values visible inside the sandbox. Secret values themselves are never written to qualification evidence.

It also verifies:

- no `TYPESAFE_*` environment variable inside the sandbox;
- no Docker socket;
- no repository `.git`;
- no direct external network reachability;
- only expected qualification workspace files.

## 7. Verify qualification

~~~bash
python - <<'PY'
import json
import os

path = os.environ["QUALIFICATION"]
value = json.load(open(path, encoding="utf-8"))
assert value["qualified"] is True, value
for gate, evidence in value["gates"].items():
    assert evidence["status"] == "pass", (gate, evidence)
print("P0A qualified:", path)
PY
~~~

If any gate fails, do not start the real A/B run.

Investigate and correct the qualification failure. Under the current comparative-study checkpoint, P0B remains blocked until the authenticated P0A manifest reports `qualified: true` with IA-1 through IA-8 all passing. The direct-Docker backend remains available for parity, diagnostics, and rollback analysis, but it is not a bypass around this gate.

## 8. Re-verify frozen inputs

Before real adjudication:

~~~bash
sha256sum "$ORACLE_VIEW" "$CORPUS"
~~~

Required:

~~~text
a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a  oracle-authoring-view.json
e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280  routing-semantic-v1.corpus.json
~~~

## 9. Start real independent A/B adjudication

Use a new output root:

~~~bash
export ORACLE_RUN="$PRIVATE_ROOT/oracle-run"

"$AW" benchmark adjudication-inspect-run-primary   "$MODULE"   "$ORACLE_VIEW"   "$ORACLE_PROTOCOL"   "$RUNTIME_LOCK"   "$QUALIFICATION"   "$ORACLE_RUN"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"
~~~

The command refuses to execute if:

- the qualification is absent;
- `qualified` is false;
- qualification module identity differs;
- qualification runtime-lock SHA differs;
- requested A/B/C model differs from the model recorded by P0A IA-2.

A and B are separate Inspect samples and therefore receive separate sandbox instances.

Neither adjudication pass is written to the benchmark-owned output tree until the primary Inspect task has completed successfully.

Expected authoritative passes:

~~~text
$ORACLE_RUN/a/output/adjudication.json
$ORACLE_RUN/b/output/adjudication.json
~~~

Inspect logs remain supplementary execution evidence.

## 10. Validate A and B

~~~bash
"$AW" benchmark decision-study-adjudication-validate   "$ORACLE_VIEW"   "$ORACLE_RUN/a/output/adjudication.json"

"$AW" benchmark decision-study-adjudication-validate   "$ORACLE_VIEW"   "$ORACLE_RUN/b/output/adjudication.json"
~~~

## 11. Compute disputes only after both are complete

~~~bash
export DISPUTE_VIEW="$ORACLE_RUN/oracle-disputes-for-c.json"

"$AW" benchmark decision-study-oracle-disputes   "$ORACLE_VIEW"   "$ORACLE_RUN/a/output/adjudication.json"   "$ORACLE_RUN/b/output/adjudication.json"   "$DISPUTE_VIEW"
~~~

If `requires_c=false`, skip C.

## 12. Run C when required

C uses the **same runtime lock and same passing qualification**:

~~~bash
"$AW" benchmark adjudication-inspect-run-c   "$MODULE"   "$DISPUTE_VIEW"   "$ORACLE_PROTOCOL"   "$RUNTIME_LOCK"   "$QUALIFICATION"   "$ORACLE_RUN"   --model "$ADJUDICATION_MODEL"   "${ADJUDICATION_MODEL_ARGS[@]}"
~~~

Expected pass:

~~~text
$ORACLE_RUN/c/output/adjudication.json
~~~

C receives only the dispute view plus protocol. A/B label values are not supplied to its sandbox.

## 13. Freeze

If C was required:

~~~bash
"$AW" benchmark decision-study-oracle-freeze   "$ORACLE_VIEW"   "$ORACLE_RUN/a/output/adjudication.json"   "$ORACLE_RUN/b/output/adjudication.json"   "$ORACLE_RUN/oracle.json"   --oracle-version routing-semantic-oracle-v1.0.0   --c-view "$DISPUTE_VIEW"   --c-pass "$ORACLE_RUN/c/output/adjudication.json"
~~~

If no C was required, omit the two C arguments.

If genuine three-way conflicts remain, create the existing recorded-resolution artifact and pass `--resolutions`.

## 14. Validate final oracle

~~~bash
"$AW" benchmark decision-study-validate   "$CORPUS"   --oracle "$ORACLE_RUN/oracle.json"
~~~

Retain:

~~~text
$ORACLE_RUN/oracle.json
$ORACLE_RUN/oracle.json.manifest.json
$RUNTIME_LOCK
$QUALIFICATION
$ORACLE_RUN/**/inspect-provenance.json
$ORACLE_RUN/inspect-logs/
~~~

Only after this point may P1 live TypeSafe/Jev instrumentation begin.

## Failure rules

If P0A fails, no real oracle cohort exists yet. Fix the qualification failure and keep P0B blocked. The direct-Docker backend remains the reference/rollback implementation for diagnosis and parity; using a different backend for real oracle production would require an explicit pre-label checkpoint/runtime decision rather than bypassing the current qualification gate.

If one real Inspect primary sample fails, do not salvage one side into another cohort. Restart A and B together with a valid qualification/runtime identity.

Never combine:

- Inspect A with direct-Docker B;
- one runtime-lock A with another runtime-lock B;
- a newly resolved Codex C with an older A/B cohort.

The runtime lock, not the moving npm `latest` tag, is the cohort identity.
