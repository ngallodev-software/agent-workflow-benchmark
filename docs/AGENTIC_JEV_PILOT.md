# Agent-Directed Jev Pilot

This benchmark lane tests **agent-directed Jev** using the existing Inspect AI / Inspect SWE Codex harness.

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
redacted before the provider call and before persistence.

## Runtime identity

Before qualification or pilot execution, freeze:

~~~bash
export AGENTIC_JEV_MODEL='openai-api/codex-lb/<model-id>'
export AGENTIC_JEV_MODEL_ARGS_JSON='{"responses_api":true}'
bash scripts/agentic-jev/p0-freeze-runtime.sh
~~~

The lock binds:

- exact Codex CLI version;
- Inspect AI/SWE versions;
- coding model + model args;
- optional requested Jev model;
- frozen TypeSafe skill SHA;
- exact 24-task development manifest SHA;
- exact host-side Jev implementation SHA;
- exact TypeSafe SDK version;
- host-tool receipt contract;
- Docker identity.

The qualification and run both assert the same lock.

## Tool qualification

Run one live synthetic tool call before spending the 24 × 3 pilot:

~~~bash
bash scripts/agentic-jev/p0-qualify-tool.sh
~~~

Required:

- one Codex invocation of `jev_system_one`;
- exactly one successful private receipt;
- `TYPESAFE_API_KEY` absent from the Codex transcript;
- skill SHA matches the lock.

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
- Jev tool-call count;
- Choice/Noul/Score mix;
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
