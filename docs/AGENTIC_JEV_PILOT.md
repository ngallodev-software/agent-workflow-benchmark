# Agent-Directed Jev Pilot

This benchmark lane tests **agent-directed Jev** using the existing Inspect AI / Inspect SWE Codex harness.

The coding agent is frozen to **GPT-6 Luna** at **high** reasoning effort for every arm. The model is served through the Responses API path behind codex-lb. Reasoning effort is supplied as Inspect generation configuration, not as a provider/model-construction argument.

It deliberately does not introduce a Jev-specific coding-agent harness.

## Treatment

| Arm | Codex | Frozen TypeSafe skill | Live Jev tool |
| --- | --- | --- | --- |
| A-baseline | yes | no | no |
| B-skill-only | yes | yes | no |
| C-skill-plus-jev | yes | yes | yes |

Arm B isolates behavior changes caused by the skill instructions from behavior changes caused by live Jev judgments.

The TypeSafe skill is frozen from `typesafe-ai/skills` commit
`65a39f393687675ce170e6094757de20370365b9` / release `v0.5.7`.

## Jev bridge

Arm C receives one Inspect bridged tool: `jev_system_one`.

The tool executes on the host and calls the TypeSafe SDK. The Codex sandbox has no
TypeSafe credential and no direct external network access.

The tool accepts bounded JSON state plus one or more typed questions:

- `choice`;
- `noul`;
- `score`.

It returns normalized typed answers, probabilities/confidence when supplied,
request identity, model identity, duration, and usage.

Private receipts record sanitized state/question shapes and secret-like fields are
redacted before the provider call and before persistence. The receipt stream is also
the authoritative execution ledger for the bridged Jev tool. Inspect/Codex may expose
only the CLI's outer local tool names (for example `exec`) in the final message
transcript, while the host-side bridge executes `jev_system_one`. With
`BridgedToolsSpec(require_proposal=True)` (the default used by this pilot), a host
execution is authorized only by a model-proposed bridged call. Contract-validation
failures are receipted as failures so attempted Jev use is not lost from pilot metrics.

## Runtime identity

Before qualification or pilot execution, freeze:

~~~bash
export AGENTIC_JEV_MODEL='openai-api/codex-lb/gpt-6-luna'
export AGENTIC_JEV_REASONING_EFFORT='high'
export AGENTIC_JEV_MODEL_ARGS_JSON='{"responses_api":true}'
bash scripts/agentic-jev/p0-freeze-runtime.sh
~~~

The lock binds:

- exact Codex CLI version, requiring >= `0.155.0`;
- Codex internal model configuration `gpt-6-luna`;
- Inspect AI/SWE versions;
- coding model `openai-api/codex-lb/gpt-6-luna`;
- coding-agent reasoning effort `high`;
- Responses API provider argument;
- optional requested Jev model;
- frozen TypeSafe skill SHA;
- exact 24-task development manifest SHA;
- exact host-side Jev implementation SHA;
- exact benchmark Inspect-harness implementation SHA;
- exact TypeSafe SDK version;
- host-tool receipt contract;
- Docker/Compose identity;
- resolved local sandbox image identity for `python:3.12-bookworm`.

All three treatment arms use the exact same Luna model, reasoning effort, Codex model configuration, and provider path. The only treatment changes across A/B/C are the frozen TypeSafe skill and live Jev availability.

The qualification and run both assert the same lock. Loading the lock rechecks the current Inspect AI / Inspect SWE versions, Codex platform, Docker/Compose identity, sandbox-image identity, benchmark Inspect-harness SHA, host-tool implementation SHA, TypeSafe SDK version, skill SHA, and task-manifest SHA before execution.

The sandbox image must already be materialized locally before the runtime is frozen so its exact image ID/digest set can be recorded. The mutable tag alone is not treated as a frozen identity.

## Tool qualification

Run one live synthetic tool call before spending the 24 × 3 pilot:

~~~bash
bash scripts/agentic-jev/p0-qualify-tool.sh
~~~

Required:

- exactly one bridged Jev execution, evidenced by exactly one host-tool receipt;
- that receipt has `status=success`;
- `TYPESAFE_API_KEY` is absent from the Codex transcript;
- skill SHA matches the lock.

Outer Codex transcript tool names are retained for diagnostics but are not used to
count Jev executions because the CLI may represent the bridge through its local
`exec` surface.

Do not proceed if this qualification fails.

## Exploratory pilot

After inspecting a passing qualification:

~~~bash
bash scripts/agentic-jev/p1-run-pilot.sh
~~~

The same 24 file-backed tasks run independently in all three arms.

Private authoring tags represent plausible opportunities such as interaction
policy, test prioritization, retrieval relevance, evidence sufficiency, strategy
selection, and semantic risk. Those tags are not exposed to Codex.

The run records:

- per-arm sample success/error counts;
- Jev host-execution count from the private receipt ledger;
- Choice/Noul/Score mix, including locally rejected contract attempts where identifiable;
- private request receipts;
- request status;
- latency;
- token usage;
- frozen skill/runtime/task identities.

## Claim boundary

This pilot is exploratory.

It does **not** establish that Jev improves coding quality, task success, cost, or
latency. Its purpose is to discover whether agent-directed Jev is used often enough,
at sufficiently interpretable decision seams, to justify a separately preregistered
task-outcome study.

A specialized Jev agent harness should be considered only after this evidence
shows where runtime-enforced Jev would plausibly add value.
