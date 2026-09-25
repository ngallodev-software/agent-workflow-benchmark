# Prior Art and Standards — Isolated Agent Evaluation

**Reviewed:** 2026-09-25

## Summary

Most infrastructure layers already have mature standards or libraries. We should reuse them rather than grow the current routing harness into a homegrown general-purpose evaluation platform.

| Layer | Prior art / standard | Direction |
| --- | --- | --- |
| Container format/runtime | OCI | Adopt as portability baseline |
| Local multi-container topology | Docker Compose Specification | Prefer for declarative local topology |
| Evaluation framework | Inspect AI | Current adjudication execution framework; evaluate broader benchmark use after this study |
| CLI-agent adapter layer | Inspect SWE | Current Codex CLI adapter package under Inspect AI |
| Future coding-agent scaffold | mini-SWE-agent | Prefer as the default SWE-agent-family direction for future coding-agent experiments |
| Sandbox execution abstraction | SWE-ReX | Possible lower-level portability/parallelism layer where a full evaluation framework is unnecessary |
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

This overlaps heavily with Agent-Workflow Benchmark infrastructure.

For `routing-semantic-v1`, Inspect is no longer only a candidate: the current adjudication runtime is implemented as `Inspect AI -> Inspect SWE -> inspect_swe.codex_cli() -> Codex CLI`. Inspect owns execution infrastructure while Agent-Workflow Benchmark retains the frozen module, adjudication, oracle, and evidence contracts.

For later generalized benchmark execution, Inspect remains the leading framework to evaluate when a full orchestration layer is warranted. Any migration must preserve Agent-Workflow's frozen study/evidence contracts rather than replacing them implicitly with Inspect-native scoring semantics.

## SWE-ReX

SWE-ReX provides a runtime interface for sandboxed shell environments across local/Docker and remote/cloud backends, including parallel execution.

This maps closely to the **runtime layer** of the isolated-agent architecture.

SWE-ReX is a strong candidate when we want:

- portable execution backends;
- many parallel agent environments;
- less direct Docker lifecycle code;
- no commitment to a larger evaluation framework.

It does not replace Agent-Workflow Benchmark's study contracts, scoring, sealing, publication, or A/B/C coordination.

## Inspect SWE, mini-SWE-agent, legacy SWE-agent, and OpenHands

These occupy different architectural roles and should not be conflated.

**Inspect SWE** is the package used by the current adjudication implementation. It supplies software-engineering/CLI-agent integrations for Inspect AI, including the Codex CLI adapter used here. In this study it is an adapter layer, not a replacement for Agent-Workflow Benchmark's A/B/C contracts.

**mini-SWE-agent** is the preferred SWE-agent-family direction to evaluate for future coding-agent scaffolds. Its current documentation positions it as the simpler research/evaluation-oriented agent from the team behind SWE-agent, with multiple execution backends including direct container environments and SWE-ReX-backed environments.

**Legacy SWE-agent** remains useful prior art when studying tool-rich agent scaffolds and runtime separation, but it is no longer the default future scaffold for this project. Do not replace the current Inspect SWE Codex adapter with mini-SWE-agent merely because mini-SWE-agent is the newer SWE-agent-family direction; they solve different layers of the architecture.

**SWE-ReX** remains relevant as a lower-level portable execution abstraction when Agent-Workflow Benchmark needs runtime portability or parallelism without adopting a broader evaluation framework.

**OpenHands** includes a mature sandbox/runtime system but is a broader agent platform; adopting its control plane would introduce more coupling than is needed here.

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

For `routing-semantic-v1`, the decision was amended on 2026-09-25 **before any real A/B labels or live comparative inference existed**:

1. keep the merged direct-Docker runner as the rollback/reference implementation;
2. use the implemented `Inspect AI + Inspect SWE + Codex CLI` adjudication runtime from benchmark commit `7c3cef0ca3572005cb1266629b62dcbf65608440`;
3. complete authenticated Debian-host qualification against the actual model/load-balancer path using synthetic fixtures only;
4. require the frozen qualification manifest to report `qualified: true` with IA-1 through IA-8 all passing;
5. preserve the frozen corpus/view/oracle protocol unchanged;
6. keep P0B real A/B adjudication blocked until the qualification gate passes.

See `docs/plans/2026-09-25-inspect-adjudication-integration-plan.md`.

For later generalized benchmark execution, evaluate the same Inspect backend after the routing study is complete. For future software-engineering agent scaffolds, evaluate mini-SWE-agent before legacy SWE-agent. SWE-ReX remains a candidate when a lower-level portable runtime abstraction is preferable to Inspect's broader evaluation orchestration.

The goal is to reuse mature infrastructure while retaining the evidence model that makes Agent-Workflow Benchmark valuable.
