# Inspect Adjudication Runtime — Implementation Record

**Date:** 2026-09-25  
**Benchmark release:** `0.4.1`  
**Status:** implementation complete; authenticated Debian-host P0A qualification still required

## Purpose

This record documents the implementation of the Inspect AI / Inspect SWE adjudication backend planned in:

`docs/plans/2026-09-25-inspect-adjudication-integration-plan.md`

The implementation occurred before any real `routing-semantic-v1` A/B oracle labels or live TypeSafe/Jev treatment inference.

## What was implemented

- optional `agent-workflow-benchmark[inspect]` dependency group;
- pinned `inspect-ai==0.3.268`;
- pinned `inspect-swe==0.2.70`;
- A/B/C module schema v2 with `runtime.kind=inspect-ai`;
- concrete `routing-semantic-v1.inspect.module.json`;
- cohort runtime-lock contract;
- `latest-at-cohort-start` Codex policy;
- exact npm `@openai/codex` latest resolution before Inspect SWE cache population;
- separate Inspect Docker sandbox per adjudicator sample;
- sandbox `network_mode: none`;
- host-side Inspect model/provider bridge;
- no model-provider secret injection into adjudicator sandbox;
- web search disabled;
- goals disabled;
- no MCP servers;
- no bridged host tools;
- no auto-review/guardian capability;
- one attempt per oracle adjudicator;
- existing adjudication-pass/v1 result adaptation;
- existing A/B dispute and oracle-freeze contracts retained;
- synthetic P0A qualification suite;
- qualification manifest contract;
- real A/B/C execution gate requiring a matching passing qualification manifest;
- direct-Docker reference/rollback backend retained;
- direct-Docker Codex policy changed from a stale repository pin to latest-at-image-build with image reuse for the cohort;
- common adjudicator prompt shared by direct-Docker and Inspect backends;
- Debian operator guide.

## Codex version policy

Codex CLI is intentionally not pinned in source.

At cohort start:

1. query the current `@openai/codex` npm latest metadata;
2. resolve it to an exact numeric version;
3. ask Inspect SWE to download/cache that exact version;
4. record the exact version and cached binary identity in `adjudication-runtime-lock/v1`;
5. reuse that exact version for A, B, and any required C.

This avoids both failure modes:

- a repository pin becoming stale before execution;
- separate adjudicators silently resolving different same-day Codex releases.

The runtime lock becomes the cohort identity.

## Synthetic qualification

The authenticated host command is:

~~~bash
agent-workflow benchmark adjudication-inspect-qualify-live \
  modules/abc-adjudication/routing-semantic-v1.inspect.module.json \
  /private/runtime-lock.json \
  /private/qualification.json \
  --model '<inspect-model-spec>'
~~~

It uses only synthetic cases whose IDs begin with `inspect-qualification-`.

It does **not** generate labels for the frozen real 120-case authoring view.

Qualification covers:

- IA-1 dependency/runtime identity;
- IA-2 live model-provider bridge;
- IA-3 sandbox guardrails;
- IA-4 module/input/prompt materialization parity;
- IA-5 deterministic direct-wrapper/Inspect adapter contract parity;
- IA-6 independent synthetic A/B;
- IA-7 forced synthetic disagreement and fresh C;
- IA-8 synthetic oracle freeze and rollback compatibility.

## Sandbox guardrail probe

The deterministic probe executes inside an actual Inspect Docker sandbox.

It verifies:

- no direct external network reachability;
- no Docker socket;
- no repository `.git`;
- no `TYPESAFE_*` environment variables;
- no host secret-like value exposed in the sandbox;
- expected workspace allowlist materialization.

Host secret values are never persisted. The probe computes SHA-256 values on the host and compares them inside the sandbox, recording only variable names if a value unexpectedly matches.

CI runs this probe with Inspect's mock model provider and no real credentials.

## Real-run gate

`adjudication-inspect-run-primary` and `adjudication-inspect-run-c` require:

- a v2 Inspect module;
- a runtime lock bound to the exact module SHA;
- a qualification manifest with `qualified: true`;
- all IA-1 through IA-8 gates marked `pass`;
- a qualification runtime-lock SHA matching the supplied runtime lock.

The internal synthetic qualification runner has the only explicit unqualified bypass.

## Authority retained by Agent-Workflow Benchmark

Inspect remains runtime infrastructure only.

The benchmark continues to own:

- role identity;
- input/view identity;
- delayed A/B reveal;
- adjudication-pass contract;
- dispute extraction;
- C-only dispute routing;
- two-of-three resolution;
- explicit unresolved conflicts;
- oracle freeze;
- study gate.

## Frozen study semantics

This implementation does not change:

- the 120-case corpus;
- the canonical blinded A/B view;
- oracle taxonomy or label definitions;
- oracle protocol;
- TypeSafe/Jev treatment;
- statistical metrics;
- reporting semantics.

The canonical hashes remain:

- corpus: `e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280`;
- authoring view: `a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a`.

## Current boundary

Repository/CI implementation may be considered complete when this branch is merged.

P0A itself is **not complete** until the user's Debian study host executes:

1. runtime-lock creation;
2. authenticated synthetic live qualification against the intended load balancer/model;
3. all IA-1 through IA-8 gates pass;
4. the resulting qualification manifest is retained/frozen.

No real A/B oracle run should start before that host qualification passes.
