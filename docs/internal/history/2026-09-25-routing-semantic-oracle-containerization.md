# Historical Record — Routing Semantic Oracle Containerization

**Date:** 2026-09-25  
**Study:** `routing-semantic-v1`  
**Repository:** `agent-workflow-benchmark`

## Why this exists

The frozen comparative-decision protocol requires an oracle created independently of deterministic-control and TypeSafe/Jev treatment outputs.

The original operational question was whether independent coding agents needed separate physical machines or whether isolated sessions/worktrees were sufficient.

The answer adopted for this study was:

> independence is an information-flow property, not a physical-machine requirement.

Two agents may run on one Debian host when the runtime prevents them from seeing each other's work, treatment evidence, hidden corpus construction data, or unrelated credentials.

## Why Git worktrees were not sufficient

Git worktrees isolate working directories but share repository history and refs. A shell-capable agent can potentially inspect:

- other refs and branches;
- sibling worktrees;
- the common Git object database;
- local benchmark artifacts;
- repository files it was not intended to receive.

That is broader visibility than a blinded oracle adjudicator requires.

## Container decision

PR #35 added a Docker/OCI adjudication harness that gives every adjudicator:

- a fresh container;
- a private read-only input directory;
- a private writable output directory;
- a read-only root filesystem;
- no repository checkout;
- no Docker socket;
- no sibling mount;
- no deterministic-control evidence;
- no TypeSafe/Jev evidence;
- no prior adjudicator labels;
- an ephemeral Codex home;
- a narrowly scoped model-provider configuration.

A and B use the same image and run concurrently. Their outputs are not compared until both have completed.

C is created only after A/B comparison and receives only disputed cases/seams.

## Credential correction

The initial idea included supplying the containers with `TYPESAFE_API_KEY`.

That is incorrect for oracle production.

The oracle is deliberately produced before treatment inference. Therefore TypeSafe credentials provide no legitimate adjudicator capability and create unnecessary leakage risk.

The adjudicator runtime explicitly rejects `TYPESAFE_*` variables.

The TypeSafe credential is introduced only later, after the oracle is frozen, when the live comparative inference run begins.

## Frozen identities

For routing-semantic-v1:

- corpus SHA-256: `e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280`
- A/B authoring-view SHA-256: `a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a`
- oracle protocol: `routing-semantic-oracle-v1.0.0`

The preparation script refuses changed corpus/view identities.

## Modularization decision

After the first Docker harness was merged, the pattern was generalized as a declarative A/B/C module.

The module instance records:

- task identity;
- prompt;
- required files and hashes;
- runtime/image/agent version;
- roles;
- credential policy;
- guardrails;
- output schema;
- reveal/disagreement policy;
- result locations.

The routing module is:

`modules/abc-adjudication/routing-semantic-v1.module.json`

The frozen runner remains the historical executor for this study. The module contract is intended for a future generic runner and other studies after parity validation.

## Reusable pattern

The reusable architecture is:

```text
hash-bound task envelope
        |
isolated independent agents
        |
structured outputs
        |
delayed cross-agent reveal
        |
policy-driven comparison
        |
optional targeted tiebreak
        |
frozen result + provenance
```

Potential future uses include benchmark scoring panels, blind implementation arms, independent reviewers, dataset labeling, and result verification.

## Prior-art conclusion

This design is not a new container standard.

It sits on existing standards and prior art:

- OCI container image/runtime specifications;
- Docker Compose for declarative local service isolation;
- Inspect AI for evaluation/sandbox orchestration;
- SWE-ReX for portable sandbox execution.

No broadly adopted formal standard was identified for the exact independent blinded A/B/C majority/discussion protocol. That protocol remains a versioned study-level module layered above standard runtime primitives.
