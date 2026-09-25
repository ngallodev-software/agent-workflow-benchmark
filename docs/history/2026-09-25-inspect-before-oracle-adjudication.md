# Historical Amendment — Inspect Integration Before Oracle Adjudication

**Date:** 2026-09-25  
**Applies to:** `routing-semantic-v1` oracle execution infrastructure  
**Does not change:** frozen study/corpus/oracle semantics

## Prior state

The project first implemented a direct-Docker A/B/C adjudication harness and retained it as the reference runtime.

It then generalized the configuration into `abc-adjudication-module/v1` and documented Inspect AI as the leading future orchestration candidate.

The initial recommendation was to finish the routing study on the direct-Docker runner and evaluate Inspect later.

## Amendment

Before any real A/B labels or live TypeSafe/Jev comparative inference were produced, the project changed the sequencing decision:

> Integrate and qualify Inspect AI before the first real oracle adjudication, while preserving the direct-Docker implementation as a rollback/reference backend.

This is an infrastructure qualification change, not a result-affecting semantic change.

## Rationale

Inspect already supplies mature primitives that overlap with custom runner responsibilities:

- Docker sandbox lifecycle;
- sandboxed CLI-agent execution;
- model-provider abstraction;
- sandbox-to-host model bridging;
- evaluation logs;
- retries/resume/checkpointing;
- multi-task orchestration;
- concurrency/resource controls.

Inspect SWE supplies a Codex CLI adapter that runs the real CLI in the sandbox and routes its model calls through Inspect.

The bridge creates a cleaner credential boundary: the sandboxed CLI can call an Inspect loopback proxy while the actual load-balancer credential remains host-side.

Since no empirical oracle labels existed, this was the lowest-risk point to qualify the better runtime abstraction.

## Frozen rollback points

- direct-Docker adjudication harness: benchmark commit `0f5df45957eee12d6318b5a4b4590398aedc8083`;
- module/architecture baseline: benchmark commit `ac593ca879607bfd5ccbde81666fcb3c31b9aaa1`;
- canonical oracle handoff: comparative-eval commit `5652d24cdbd90c9d78c6ec5f9d7ddd39b008e15e`.

## New sequence

~~~text
P0A  Inspect integration + synthetic parity/guardrail qualification
  |
  v
P0B  real independent A/B/C oracle
  |
  v
P1   development TypeSafe/Jev instrumentation
  |
  v
P2   full 120-case preregistered run
  |
  v
P3   sanitized publication
~~~

## Qualification rule

The real 120-case A/B authoring view must not be used to generate oracle labels during P0A.

Inspect becomes the preferred backend only after synthetic qualification proves parity of:

- allowed inputs;
- prompt/output contracts;
- credential isolation;
- A/B delayed reveal;
- C dispute-only visibility;
- failure semantics;
- evidence/provenance reconstruction.

If Inspect fails, P0B starts fresh using the direct-Docker reference implementation.

## Cohort integrity rule

Do not mix an Inspect A pass with a direct-Docker B pass for the same oracle cohort.

If execution fails after only one real adjudicator pass completes, discard that incomplete cohort from oracle construction and restart both A and B under one qualified backend/runtime identity.

## Canonical plan

See:

`docs/plans/2026-09-25-inspect-adjudication-integration-plan.md`
