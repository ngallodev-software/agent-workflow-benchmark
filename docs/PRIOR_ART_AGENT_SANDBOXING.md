# Prior Art and Standards — Isolated Agent Evaluation

**Reviewed:** 2026-09-25

## Summary

Most infrastructure layers already have mature standards or libraries. We should reuse them rather than grow the current routing harness into a homegrown general-purpose evaluation platform.

| Layer | Prior art / standard | Direction |
| --- | --- | --- |
| Container format/runtime | OCI | Adopt as portability baseline |
| Local multi-container topology | Docker Compose Specification | Prefer for declarative local topology |
| Evaluation framework | Inspect AI | Strong candidate for future benchmark orchestration |
| Sandbox execution abstraction | SWE-ReX | Strong candidate for runtime portability/parallelism |
| Exact A/B/C blinded adjudication | No broadly adopted formal standard identified | Keep as versioned module |

## OCI

The Open Container Initiative defines industry specifications for container images, runtime configuration/lifecycle, and distribution.

Our Docker image is therefore already based on a formal portability standard.

Design implication:

- keep images OCI-compatible;
- express task semantics outside the image;
- permit future OCI-compatible runtimes without changing study contracts.

## Docker Compose

Compose is a declarative specification for services, networks, volumes, configs, secrets, capabilities, and security options.

It maps naturally to the isolation envelope currently expressed by repeated `docker run` flags.

Future generic local execution should consider Compose so security and mount topology become reviewable configuration rather than shell construction.

Compose does not replace task/evaluation semantics, result contracts, or A/B/C coordination.

## Inspect AI

Inspect AI provides:

- datasets/samples;
- agent/solver abstractions;
- scorers;
- Docker and other sandbox environments;
- per-sample files/setup;
- multi-agent workflows;
- limits/retries/resumption;
- evaluation logs and analysis;
- integrations for coding agents including Codex CLI and Claude Code via Inspect SWE.

This overlaps heavily with future Agent-Workflow Benchmark infrastructure.

Inspect is therefore the leading candidate when we need a full evaluation orchestration framework rather than only a sandbox abstraction.

Migration must preserve Agent-Workflow's frozen study/evidence contracts rather than replacing them implicitly with Inspect-native scoring semantics.

## SWE-ReX

SWE-ReX provides a runtime interface for sandboxed shell environments across local/Docker and remote/cloud backends, including parallel execution.

This maps closely to the **runtime layer** of the isolated-agent architecture.

SWE-ReX is a strong candidate when we want:

- portable execution backends;
- many parallel agent environments;
- less direct Docker lifecycle code;
- no commitment to a larger evaluation framework.

It does not replace Agent-Workflow Benchmark's study contracts, scoring, sealing, publication, or A/B/C coordination.

## OpenHands and SWE-agent

Both are useful architecture references.

SWE-agent uses SWE-ReX for its runtime isolation. That reinforces the separation between agent logic and execution infrastructure.

OpenHands includes a mature sandbox/runtime system but is a broader agent platform; adopting its control plane would introduce more coupling than is needed here.

## Is there a standard for A/B/C adjudication?

Not in the same sense as OCI or JSON Schema.

The exact policy used here is methodological:

1. A and B independently label the same blinded input.
2. Neither sees the other's result before completion.
3. Only disagreements go to C.
4. Two-of-three agreement resolves a disagreement.
5. True three-way conflicts use a recorded discussion.
6. Unresolvable conflicts remain explicit rather than forcing a label.
7. The oracle/result freezes before treatment inference.

This should remain a versioned module contract.

## Recommendation

For `routing-semantic-v1`:

- use the merged Docker reference runner;
- do not swap execution framework mid-study.

For the next generalized benchmark runner:

1. start from the declarative isolated-agent/module contract;
2. prototype the same task in Inspect AI with Docker sandbox;
3. prototype the runtime layer with SWE-ReX if backend portability matters;
4. run a parity cohort against the existing runner;
5. compare input hashes, output contracts, isolation, failure semantics, timing, token evidence, and final manifests;
6. adopt the external framework only if evidence parity is demonstrated.

The goal is to reuse mature infrastructure while retaining the evidence model that makes Agent-Workflow Benchmark valuable.
