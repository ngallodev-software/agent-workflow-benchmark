# Agent-Directed Jev Pilot

This lane tests **agent-directed Jev** without building a Jev-specific coding harness.

~~~text
A  Codex baseline
B  Codex + frozen TypeSafe skill
C  Codex + same skill + host-side Jev bridged tool
~~~

The skill is frozen from `typesafe-ai/skills` commit
`65a39f393687675ce170e6094757de20370365b9` / release `v0.5.7`.

The Jev tool executes on the host through Inspect bridged-tools/MCP. The Codex
sandbox does not receive `TYPESAFE_API_KEY`.

## Phase 0 — freeze treatment/runtime

Choose the coding-agent model explicitly:

~~~bash
export AGENTIC_JEV_MODEL='openai-api/codex-lb/<model-id>'
# Model args are also frozen; default is explicit Responses API use.
export AGENTIC_JEV_MODEL_ARGS_JSON='{"responses_api":true}'

bash scripts/agentic-jev/p0-freeze-runtime.sh
~~~

The lock freezes:

- exact Codex CLI version;
- Inspect AI/SWE versions;
- coding model and model args;
- optional Jev model request;
- TypeSafe skill SHA/upstream identity;
- exact 24-task development manifest;
- host-tool contract;
- Docker identity.

Do not regenerate the lock mid-pilot.

## Phase 0 — qualify the host-side Jev bridge

With `TYPESAFE_API_KEY` present only on the host:

~~~bash
bash scripts/agentic-jev/p0-qualify-tool.sh
~~~

This runs one synthetic Arm-C sample and requires:

- Codex actually calls the bridged `jev_system_one` tool;
- exactly one successful private tool receipt;
- the API key is absent from the agent transcript;
- the frozen skill snapshot matches the runtime lock.

**Stop here and inspect the qualification before the 24×3 pilot.**

## Phase 1 — exploratory 24×3 pilot

Only after qualification passes:

~~~bash
bash scripts/agentic-jev/p1-run-pilot.sh
~~~

All three arms receive the same 24 file-backed tasks. Authoring opportunity tags
are stripped before samples are constructed.

The pilot records invocation/primitive/request evidence but is explicitly
development-only. It does not score an overall winner and cannot support a
downstream software-quality claim.

The intended output is a decision about which observed Jev seams deserve a
separately preregistered full task-outcome study.
