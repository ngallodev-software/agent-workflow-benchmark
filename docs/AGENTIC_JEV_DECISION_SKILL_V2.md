# Agentic Jev Decision-Skill v2

**Study identity:** `agentic-jev-decision-skill-v2`  
**Status:** DEVELOPMENT-ONLY / treatment correction  
**Predecessors:** `agentic-jev-pilot-v1`, `agentic-jev-external-eval-scout-v1`

## Skill source and benchmark adaptation

The benchmark `jev-decision-support` skill is now derived from the standalone
public skill repository:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `65b444965e48209860e353f2aa0e8d9dbe35d2ce`
- source path: `skills/jev-decision-support/SKILL.md`

The derivative intentionally preserves the source skill's stronger agent-facing
structure:

- decide among plausible alternatives after inspecting facts;
- project only relevant decision context;
- keep exact specifications/tests/user instructions authoritative;
- support Choice, Noul, and Score;
- reconcile semantic advice with deterministic evidence;
- avoid unchanged retries seeking a preferred answer;
- treat tool execution as evidence of use, not evidence of effectiveness.

The benchmark adds stricter transport and evidence rules:

- live inference must use the already-qualified host-side `jev_system_one` bridge;
- the coding-agent sandbox must not install/use the SDK, call the TypeSafe API
  directly, request credentials, or create another transport;
- the skill describes the benchmark host limits (16 questions, 64 KiB state,
  48 KiB question payload);
- one call per decision seam is the default;
- the skill's `agents/openai.yaml` discovery metadata is hash-bound alongside
  `SKILL.md`;
- the v2 runtime lock records the exact public source repository, commit, and path.

The standalone repository's callable SDK helper is deliberately not copied into the
benchmark treatment. It is useful for normal installations, but a second live
transport would weaken the benchmark's host-only credential boundary and make Jev
execution accounting ambiguous.

The local provenance note is:
`src/agent_workflow_benchmark/assets/agentic-jev-decision-v2/SOURCE.md`.

## Why v2 exists

The first Agentic-Jev treatment used two components in Arm C:

1. the frozen upstream `typesafe-ai` skill;
2. the live host-side `jev_system_one` bridged tool.

The bridge was successfully qualified, but Luna made zero Jev calls across:

- 24/24 original C-arm development tasks;
- 6/6 SWE-Lancer manager proposal-selection tasks.

The repeated zero uptake exposed a treatment-design mismatch.

The frozen upstream skill is a **TypeSafe integration/build skill**. Its discovery
metadata says to use it when building AI-powered software with TypeSafe, replacing
prompt-and-parse integration steps, or exploring routing/ranking/extraction and
similar product features. Its body emphasizes live TypeSafe docs, SDK/API
integration, and application architecture.

It does not describe the workflow under test:

> the coding agent itself has a host-side Jev tool available and may delegate one
> bounded semantic decision to it while solving another task.

It also does not name `jev_system_one` or explain how to construct a call to the
bridged tool.

This matters because Codex skill discovery uses the skill name/description as the
first routing signal. A skill aimed at product integration is not a reliable
affordance for an agent-side decision workflow.

The original zero-call results remain valid evidence for the original treatment.
They are not rewritten or discarded.

## v2 treatment

v2 is additive.

It keeps:

- GPT-6 Luna / high;
- the exact Codex runtime identity;
- the original frozen upstream `typesafe-ai` skill;
- the same host-side `jev_system_one` implementation;
- the same TypeSafe SDK version;
- the same host-only credential boundary;
- the same generic Codex system prompt.

It adds one new skill:

~~~text
jev-decision-support
~~~

The skill is intentionally narrow. Its discovery description says to use it when
the coding agent itself faces a bounded semantic judgment among multiple plausible
alternatives and the Jev bridged tool is available.

Canonical triggers include:

- competing implementation proposals;
- ambiguous intended behavior;
- interaction-policy choices;
- evidence sufficiency;
- semantic risk comparisons.

It explicitly excludes deterministic facts, exact lookups, tests, calculations,
and routine execution.

## Decision rule taught by the skill

The skill asks the agent to check three conditions before finalizing a semantic
choice:

1. more than one option remains plausible;
2. deterministic evidence does not identify a single answer;
3. the choice materially affects implementation, review, UX, behavior, evidence,
   or risk.

If all three hold and `jev_system_one` is available, the agent should call it
once before finalizing.

Competing implementation proposals are named as the canonical Choice case.

The Jev result remains advisory. Exact specifications, tests, and invariants retain
authority if they contradict the semantic judgment.

## Two-stage qualification

The old bridge qualification proved that the host tool works when the task directly
orders a Jev call. That is necessary but not sufficient for a skill-mediated
experiment.

v2 therefore adds a separate **skill-activation qualification**.

The qualification task presents a bounded implementation choice with three
proposals. The task prompt itself contains neither `Jev` nor `TypeSafe`.

The exact same task is executed twice:

~~~text
control:
  frozen upstream TypeSafe skill + live Jev tool

treatment:
  frozen upstream TypeSafe skill
  + jev-decision-support skill
  + live Jev tool
~~~

Both executions use the same model, runtime, system prompt, and bridge.

The v2 qualification passes only if the **treatment**:

- records exactly one Jev host receipt;
- records exactly one successful Jev receipt;
- keeps `TYPESAFE_API_KEY` out of the agent transcript.

The control result is recorded but is not required to remain at zero. If control is
zero and treatment is one, `activation_lift_observed=true`.

This qualification tests skill-mediated uptake, not model quality.

## Operator sequence

Do not rerun the six manager tasks yet.

First freeze the additive v2 treatment:

~~~bash
bash scripts/agentic-jev/p3-freeze-decision-skill-v2.sh
~~~

Then run the activation qualification:

~~~bash
bash scripts/agentic-jev/p3-qualify-decision-skill-v2.sh
~~~

Stop and inspect the output.

Only after a passing activation qualification may the six frozen manager tasks be
rerun under v2:

~~~bash
bash scripts/agentic-jev/p3-run-manager-v2.sh
~~~

The v2 manager run is written under a new evidence root. It does not overwrite the
zero-call manager run from the original treatment.

## Interpretation boundary

A passing activation qualification shows that the new skill can cause Luna to
recognize an appropriate tool-use seam without the task explicitly naming Jev.

A nonzero manager uptake result would establish treatment exposure, not
effectiveness.

A zero manager uptake result after a passing activation qualification would be much
stronger evidence that even an explicit agent-facing decision workflow does not
generalize from the synthetic activation seam to these real proposal-selection
tasks.

No v2 result supports a claim that Jev improves or harms software-engineering
quality until a separately designed scored comparative study is run.
