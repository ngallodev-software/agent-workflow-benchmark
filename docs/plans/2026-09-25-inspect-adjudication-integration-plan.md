# Inspect AI Integration Plan for Independent Oracle Adjudication

**Date:** 2026-09-25  
**Status:** approved implementation plan; integration required before first real A/B oracle pass  
**Primary repository:** `agent-workflow-benchmark`  
**Study:** `routing-semantic-v1`

## Decision

Integrate Inspect AI as the preferred execution/orchestration backend for the independent A/B/C adjudication workflow **before producing any real oracle labels**.

The already-merged direct-Docker adjudication harness remains the frozen reference/rollback implementation. It is not deleted or rewritten.

This plan changes **execution infrastructure only**. It does not change:

- the 120-case frozen corpus;
- the blinded A/B authoring view;
- the oracle rubric;
- the A/B/C independence protocol;
- task-class labels;
- interaction-required semantics;
- semantic-risk semantics;
- disagreement/majority rules;
- unresolved-conflict handling;
- oracle freeze-before-inference requirement;
- TypeSafe/Jev treatment behavior;
- statistical policy;
- publication criteria.

No adjudication labels or live comparative inference have been produced yet, so this infrastructure change can be qualified before empirical study execution without invalidating a result-bearing artifact.

## Rollback anchors

The following commits are explicit rollback/reference points:

| Repository | Commit | Meaning |
| --- | --- | --- |
| `agent-workflow-benchmark` | `0f5df45957eee12d6318b5a4b4590398aedc8083` | merged direct-Docker oracle adjudication harness |
| `agent-workflow-benchmark` | `ac593ca879607bfd5ccbde81666fcb3c31b9aaa1` | declarative A/B/C module contract + isolation architecture |
| `agent-workflow-comparative-eval` | `5652d24cdbd90c9d78c6ec5f9d7ddd39b008e15e` | canonical frozen oracle-authoring handoff |

If Inspect integration does not meet the parity gates in this plan, return to the direct-Docker backend at these commits rather than weakening the study protocol.

## Frozen study identities

These remain unchanged throughout Inspect integration:

- study: `routing-semantic-v1`;
- study version: `1.1.0`;
- dataset: `routing-semantic-corpus-v1.0.0`;
- corpus SHA-256: `e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280`;
- blinded A/B view SHA-256: `a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a`;
- oracle protocol: `routing-semantic-oracle-v1.0.0`.

Inspect integration must verify these identities. It must not regenerate or mutate them.

## Why integrate before adjudication?

The direct-Docker harness proved the information-flow design, but Inspect already supplies mature primitives for:

- isolated Docker sandboxes;
- sandboxed CLI agents;
- retries/resume/checkpointing;
- structured evaluation logs;
- model-provider abstraction;
- agent-to-provider bridging;
- multi-task/eval-set orchestration;
- resource/concurrency controls.

Using these primitives before the first empirical adjudication avoids making the one-off runner the permanent control plane.

It also improves credential isolation: with the Inspect sandbox agent bridge, Codex inside the sandbox can target a loopback proxy while the actual model/load-balancer credential remains in the host-side Inspect process.

## Proposed pinned integration baseline

Initial implementation should pin exact versions rather than resolve moving releases:

- `inspect-ai==0.3.268`;
- `inspect-swe==0.2.70`;
- Codex CLI `latest` resolved once at cohort start, with the exact resolved version frozen in the runtime lock;
- existing Agent-Workflow Benchmark `0.4.0` contracts;
- existing comparative-eval `0.2.0` study contracts.

Inspect/Inspect-SWE pins and the **resolved** Codex CLI version are infrastructure identity and must be persisted in the adjudication run manifest.

A later dependency upgrade requires a new runtime qualification, not silent resolution.

## Target architecture

~~~text
routing-semantic-v1.module.json
            |
            v
A/B/C module validator
            |
            v
generic adjudication coordinator
            |
      +-----+------+
      |            |
      v            v
DirectDocker   InspectBackend
(reference)    (preferred)
                    |
                    v
              Inspect Task/Sample
                    |
                    v
              Docker sandbox
                    |
                    v
          inspect_swe.codex_cli()
                    |
                    v
        sandbox agent bridge proxy
             localhost only
                    |
                    v
        host-side Inspect model API
                    |
                    v
       user OpenAI-compatible load balancer
                    |
                    v
          model response / usage
                    |
                    v
       existing adjudication-pass/v1
                    |
                    v
existing A/B compare -> C -> freeze
~~~

The coordinator remains Agent-Workflow Benchmark authority. Inspect executes isolated agent work; it does not own oracle semantics.

## Authority boundaries

### Agent-Workflow Benchmark continues to own

- module validation;
- frozen input identity verification;
- role assignment;
- A/B delayed reveal;
- disagreement extraction;
- C-only dispute routing;
- majority/discussion policy;
- unresolved-conflict representation;
- adjudication-pass contract;
- final oracle assembly/freeze;
- freeze manifest;
- study/inference gating.

### Inspect owns

- sandbox lifecycle;
- CLI-agent execution;
- model bridge;
- runtime limits;
- execution logs;
- retry/resume mechanics used by the backend;
- sandbox-level isolation implementation.

### Inspect must not own

- routing taxonomy;
- oracle labels;
- final correctness;
- study scoring;
- TypeSafe/Jev treatment behavior;
- oracle majority semantics;
- publication eligibility.

## Model-provider integration

### Preferred path: OpenAI-compatible load balancer

Inspect supports an OpenAI-compatible provider using:

`openai-api/<provider-name>/<model-name>`

with host-side environment variables:

~~~text
<PROVIDER_NAME>_API_KEY
<PROVIDER_NAME>_BASE_URL
~~~

For the actual user load balancer, choose one stable provider alias and keep its key/base URL in the host environment or an external host-only env file.

The sandboxed Codex process should not receive that secret.

### Sandbox bridge

`inspect_swe.codex_cli()` uses Inspect's sandbox-agent bridge. The CLI inside the sandbox should talk to the Inspect loopback proxy instead of the load balancer directly.

Required settings:

- `web_search="disabled"`;
- `goals=false` unless proven necessary;
- no MCP servers;
- no bridged tools;
- no provider-side code execution;
- no client MCP forwarding;
- `attempts=1` for oracle independence unless the protocol is versioned to allow retries;
- Codex CLI version from the frozen cohort runtime lock (resolved from `latest` exactly once);
- explicit working directory containing only the permitted task files.

### Fallback provider path

If the load balancer is not sufficiently OpenAI-compatible:

1. implement an Inspect `ModelAPI` extension for the load balancer;
2. retain the same sandbox bridge;
3. keep provider credentials host-side;
4. do not fall back to mounting broad personal Codex credentials into the sandbox unless the provider extension is proven infeasible.

## Module evolution

Do not mutate `abc-adjudication-module/v1` in place.

Add a versioned runtime backend block or a new compatible schema version that can express:

~~~json
{
  "runtime": {
    "kind": "inspect-ai",
    "inspect_ai_version": "0.3.268",
    "inspect_swe_version": "0.2.70",
    "sandbox": {
      "provider": "docker"
    },
    "agent": {
      "kind": "inspect-swe/codex-cli",
      "version_policy": "latest-at-cohort-start"
    }
  }
}
~~~

The existing `oci-docker` module remains valid.

Preferred code architecture:

~~~text
AdjudicationRuntimeBackend
├── DirectDockerBackend
└── InspectBackend
~~~

Both backends must consume the same validated module semantics and emit the same benchmark-owned result contracts.

## Inspect task representation

Each adjudicator role should execute in a separate Inspect sample/sandbox.

A/B requirements:

- identical exact blinded authoring-view bytes;
- identical exact protocol bytes;
- same prompt template except adjudicator ID;
- separate sandbox;
- separate agent session;
- separate result path;
- no cross-sample filesystem;
- no repository;
- no other adjudicator output;
- no treatment output.

C requirements:

- created only after A and B are both complete and validated;
- receives the generated dispute-only view;
- does not receive A/B labels;
- fresh sandbox/session;
- same frozen protocol.

Do not use one continuing agent conversation for multiple roles.

## Output adaptation

Inspect-native logs are supplementary execution evidence. They are not the authoritative oracle record.

The Inspect backend must convert the agent result into the existing contract:

`agent-workflow-benchmark/decision-study-adjudication-pass/v1`

The normal benchmark validators then run unchanged.

Persist additional backend provenance separately:

- Inspect AI version;
- Inspect SWE version;
- Codex CLI version;
- Inspect task identity;
- Inspect eval/sample/run ID;
- sandbox image ID/digest;
- model/provider alias;
- input-view SHA-256;
- prompt SHA-256;
- Inspect log path/hash;
- start/end timestamps;
- token/usage data when available;
- retry/checkpoint status.

Do not persist secret values.

## Pre-adjudication qualification gates

**No real routing-semantic-v1 A/B labels may be produced until every gate passes.**

### Gate IA-1 — dependency/runtime qualification

Verify on the Debian host:

- pinned Inspect AI imports;
- pinned Inspect SWE imports;
- Docker meets Inspect's supported minimum;
- `inspect_swe` resolves the current stable Codex CLI and the resolved version launches through `inspect_swe.codex_cli()`;
- current Agent-Workflow benchmark package still installs/tests with optional Inspect dependencies.

Result: machine-readable runtime qualification artifact.

### Gate IA-2 — provider bridge qualification

Using a non-study synthetic prompt:

- Inspect reaches the user's load balancer;
- sandboxed Codex reaches only the Inspect loopback model proxy;
- load-balancer credential is absent from sandbox environment/files;
- provider model identity is recorded;
- usage/finish/error information survives to Inspect logs.

Result: provider-bridge qualification artifact.

### Gate IA-3 — guardrail qualification

In a synthetic sandbox, prove:

- no benchmark repository mount;
- no comparative-eval repository mount;
- no Docker socket;
- no sibling-agent mount;
- no `TYPESAFE_*` variable;
- no load-balancer secret;
- web search disabled;
- MCP disabled;
- provider-side code execution not granted;
- root/task visibility matches module allowlist.

Use an explicit adversarial inspection script/sample that attempts to enumerate filesystem, environment, network/tool capabilities, and known forbidden paths.

Result: guardrail report with pass/fail booleans and captured evidence.

### Gate IA-4 — module materialization parity

Using a synthetic adjudication fixture:

Compare `DirectDockerBackend` vs `InspectBackend` for:

- prompt bytes/hash;
- task-file bytes/hashes;
- adjudicator ID substitution;
- output JSON Schema;
- expected case/seam set;
- role-specific visible files;
- result path semantics.

The agent's stochastic labels do not need to be identical.

Result: parity manifest.

### Gate IA-5 — deterministic adapter parity

Use a deterministic fake/stub adjudicator executable in both backends.

Require exact equality for:

- materialized inputs;
- structured result;
- wrapper/adaptation result;
- pass-schema validation behavior;
- failure handling;
- duplicate/missing-case rejection;
- result hash calculation.

This removes model nondeterminism from backend parity testing.

### Gate IA-6 — A/B independence orchestration

Synthetic A/B run:

- launch both independently;
- coordinator must not compare/reveal until both terminate and validate;
- intentional failure of A or B must prevent comparison;
- output of one sandbox must not be mounted into the other;
- retry/resume must never convert one role into another role/session.

Result: orchestration qualification artifact.

### Gate IA-7 — C dispute isolation

Synthetic disagreement run:

- generate dispute artifact only after A/B completion;
- C receives only disputed cases/seams;
- C cannot see A/B labels;
- C has distinct adjudicator ID/session;
- three-way conflict can reach existing resolution path.

Result: C-isolation qualification artifact.

### Gate IA-8 — rollback equivalence

Before real adjudication, execute the complete synthetic fixture with both backends and archive:

- DirectDockerBackend evidence;
- InspectBackend evidence;
- comparison of contracts/guardrails;
- known differences;
- rollback instructions.

Inspect becomes preferred only if there are no study-semantic differences.

## Revised study phase map

The previous checkpoint began with:

`P0 — independent oracle`

It is now expanded without changing downstream study semantics:

### P0A — Inspect integration and parity qualification

1. Pin Inspect/Inspect-SWE versions and define Codex as `latest-at-cohort-start`.
2. Add optional benchmark dependency group.
3. Add `InspectBackend`.
4. Add load-balancer provider configuration.
5. Route Codex through Inspect sandbox bridge.
6. Extend module runtime schema/version.
7. Preserve DirectDockerBackend.
8. Implement IA-1 through IA-8 qualification gates.
9. Produce an Inspect-integration qualification manifest.
10. Mark backend `qualified=true` only if all gates pass.

**No real A/B labels are produced in P0A.**

### P0B — independent oracle

Only after P0A qualification:

1. Materialize exact frozen A/B inputs.
2. Run independent A and B through the qualified Inspect backend.
3. Validate both existing adjudication-pass artifacts.
4. Compare only after both complete.
5. Generate dispute-only C view.
6. Run C only where required.
7. Resolve true three-way conflicts under frozen protocol.
8. Freeze `oracle.json` and `oracle.json.manifest.json`.
9. Validate against frozen corpus.
10. Archive Inspect execution provenance separately.

If Inspect fails qualification or execution before valid A/B completion, roll back to DirectDockerBackend and begin fresh A/B sessions. Do not mix one backend's A pass with another backend's B pass in the same oracle unless a future protocol version explicitly permits heterogeneous adjudicator runtimes.

### P1 — development instrumentation run

Unchanged from the prior plan.

After oracle freeze, run a small live TypeSafe/Jev instrumentation check and verify one provider request/case, three observations, probability survival, no oracle during inference, no secret leakage, and correct request-level cost accounting.

### P2 — full preregistered study

Unchanged.

Run all 120 cases with the frozen oracle and identities, then report.

### P3 — sanitized publication

Unchanged.

Publish public-safe results, limitations, identities, exclusions, and evidence regardless of outcome direction.

### P4 — generic isolated-agent backend evaluation

After routing-semantic-v1 is complete, evaluate whether the same Inspect backend should replace custom container lifecycle code for:

- benchmark paired arms;
- blind implementation tasks;
- scoring/reviewer panels;
- post-seal semantic evaluators.

This must be a separate study/infrastructure decision. Do not broaden the current oracle-integration change into a BM runner rewrite before P0B.

## Implementation work breakdown

### Checkpoint I-001 — dependency seam

- add optional `inspect` dependency group;
- pin versions;
- add runtime identity helpers;
- no behavior change to current Docker path.

Acceptance:

- normal installation without Inspect remains valid;
- `[inspect]` installation works in CI/dev;
- package/version identity can be emitted.

### Checkpoint I-002 — backend interface

Create backend-neutral types/functions for:

- prepare role;
- run role;
- collect result;
- runtime provenance;
- cleanup.

Move no frozen study semantics into backend classes.

Acceptance:

- DirectDockerBackend can wrap current runner behavior without semantic change;
- unit tests use a fake backend.

### Checkpoint I-003 — Inspect task adapter

Implement:

- module -> Inspect sample/task materialization;
- private sandbox;
- Codex CLI solver;
- exact prompt/file input;
- structured result capture.

Acceptance:

- synthetic sample runs locally;
- output validates against generated JSON Schema.

### Checkpoint I-004 — provider bridge

Implement host-side provider selection for the user's load balancer.

Acceptance:

- secret absent in sandbox;
- successful bridged request;
- provider identity/usage captured;
- web/MCP/provider tools remain disabled.

### Checkpoint I-005 — evidence adapter

Convert Inspect result into existing `decision-study-adjudication-pass/v1`.

Acceptance:

- existing validators require no semantic changes;
- output SHA/hash behavior stable;
- Inspect log/provenance sidecar separate.

### Checkpoint I-006 — A/B coordinator

Run two independent Inspect evaluations/samples and block comparison until both validate.

Acceptance:

- concurrency supported;
- failure of either blocks reveal/compare;
- no cross-role visibility.

### Checkpoint I-007 — C coordinator

Generate C only from existing dispute command and run fresh Inspect session.

Acceptance:

- C input hash matches dispute view;
- A/B labels absent;
- existing freeze command accepts resulting C pass.

### Checkpoint I-008 — qualification suite

Automate IA-1 through IA-8.

Acceptance:

- single machine-readable qualification manifest;
- explicit `qualified: true|false`;
- exact runtime/library/image identities;
- no real routing corpus labels generated.

### Checkpoint I-009 — operator workflow

Add commands resembling:

~~~bash
agent-workflow benchmark adjudication-runtime-qualify \
  modules/abc-adjudication/routing-semantic-v1.inspect.module.json

agent-workflow benchmark adjudication-run-primary \
  modules/abc-adjudication/routing-semantic-v1.inspect.module.json \
  --root /private/routing-oracle

agent-workflow benchmark adjudication-compare --root /private/routing-oracle

agent-workflow benchmark adjudication-run-tiebreaker --root /private/routing-oracle

agent-workflow benchmark adjudication-freeze --root /private/routing-oracle
~~~

Exact names can change during implementation; contracts should not.

### Checkpoint I-010 — P0A freeze

Before real A/B execution:

- commit all integration code;
- merge to main;
- record exact benchmark commit;
- record Inspect/Inspect-SWE versions and the exact Codex version resolved into the cohort runtime lock;
- save qualification manifest;
- verify canonical corpus/view hashes;
- update comparative-study checkpoint.

Then begin P0B.

## CI strategy

Add two lanes:

### Standard CI

No Docker/model credentials required.

Runs:

- module/schema tests;
- fake backend tests;
- adapter unit tests;
- deterministic parity tests that do not call a model.

### Opt-in integration qualification

Runs on the Debian study host with Docker and provider credentials.

Runs:

- Inspect sandbox;
- provider bridge;
- synthetic Codex task;
- guardrail probe;
- A/B/C synthetic orchestration;
- parity qualification.

Never runs the real 120-case authoring view until P0A is explicitly frozen.

## Evidence and provenance artifacts

P0A should produce a private qualification tree similar to:

~~~text
inspect-qualification/
├── qualification-manifest.json
├── runtime.json
├── dependency-lock.json
├── direct-docker-reference/
├── inspect-backend/
├── provider-bridge/
├── guardrail-probe/
├── deterministic-parity/
├── ab-orchestration/
├── c-isolation/
└── SHA256SUMS
~~~

Public-safe status may record only:

- versions;
- hashes;
- pass/fail gates;
- non-secret configuration identity;
- limitations.

Do not publish provider credentials, raw authenticated configuration, or sensitive logs.

## Failure/rollback rules

Rollback is a normal qualification outcome, not a study failure.

Use DirectDockerBackend when:

- Inspect cannot route the user's provider correctly;
- sandbox bridge leaks credentials/capabilities;
- materialized inputs differ;
- output adaptation changes existing semantics;
- C cannot be isolated;
- Inspect retries/resume violate role independence;
- required evidence identities cannot be reconstructed.

If rollback occurs before real A/B labels: begin P0B with fresh DirectDocker sessions.

If a failure occurs after one real Inspect adjudicator pass has completed but before both A/B are valid: discard that incomplete cohort and restart both A and B together under one qualified backend. Preserve the discarded run privately as operational evidence, but do not mix it into the oracle.

## Non-goals for this integration

Do not:

- change the frozen 120 cases;
- regenerate the A/B authoring view;
- change the oracle rubric;
- expose TypeSafe/Jev to adjudicators;
- evaluate Jev before oracle freeze;
- migrate BM3-BM6 execution to Inspect in the same change;
- replace Agent-Workflow Benchmark's scorer/report contracts with Inspect scorers;
- let Inspect logs become the sole evidence authority;
- add provider tools/web/MCP for adjudicators.

## Completion criteria for P0A

P0A is complete only when:

1. Inspect backend is merged and version-pinned.
2. Direct Docker remains available.
3. All IA-1 through IA-8 gates pass.
4. Provider secrets remain host-side.
5. Synthetic A/B/C workflow completes end-to-end.
6. Existing adjudication-pass/dispute/freeze contracts remain unchanged.
7. Qualification manifest is frozen with SHA-256.
8. Canonical study/view/corpus identities still match.
9. No real A/B labels have yet been generated.
10. The canonical comparative-study checkpoint records the new P0B start point.

At that point, the next action is the real independent A/B oracle run through the qualified Inspect backend.
