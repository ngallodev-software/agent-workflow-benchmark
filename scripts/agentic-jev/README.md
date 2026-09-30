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

## Operator sequence

The normal Phase-0 path is:

~~~text
p0-freeze-runtime.sh
  -> p0-qualify-tool.sh
  -> inspect qualification.json

qualification PASS
  -> keep the runtime lock and qualification live
  -> p1-run-pilot.sh

qualification FAIL, or implementation/runtime changes before Phase 1
  -> p0-archive-attempt.sh <reason-label>
  -> update/reinstall as needed
  -> p0-freeze-runtime.sh
  -> p0-qualify-tool.sh
~~~

**Do not archive a passing current qualification before Phase 1.** It is the
authorization artifact that `p1-run-pilot.sh` verifies against the current runtime
lock.

## Phase 0 — archive a failed or superseded attempt

Use this only when a Phase-0 attempt cannot remain authoritative: for example, a
failed qualification needs to be preserved before retry, or code/runtime identity
changed after qualification and a new lock is required.

~~~bash
bash scripts/agentic-jev/p0-archive-attempt.sh tool-contract-failure
~~~

The command moves the live Phase-0 runtime lock and qualification evidence into:

~~~text
$AGENTIC_JEV_ROOT/archive/<label>/
~~~

and writes `archive-manifest.json` with source paths and evidence hashes. It
publishes the archive before deleting the live Phase-0 paths, refuses archive-label
collisions, refuses to operate after `pilot-run` exists, and refuses to archive a
passing qualification by default.

If a *passing* qualification is intentionally superseded because implementation or
runtime identity changed, require an explicit override:

~~~bash
AGENTIC_JEV_ARCHIVE_PASSING=1 \
  bash scripts/agentic-jev/p0-archive-attempt.sh superseded-runtime
~~~

That override is not part of the normal Phase-0-to-Phase-1 path.

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

- exactly one bridged Jev execution, evidenced by exactly one host-tool receipt;
- that receipt is successful;
- the API key is absent from the agent transcript;
- the frozen skill snapshot matches the runtime lock.

Outer Codex tool names are diagnostic only; the private host-tool receipt ledger is
authoritative for bridged Jev execution count.

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

## Phase 2 — external-eval uptake scout

The completed first pilot is immutable evidence. Its C arm completed 24/24 samples
with the skill and live Jev available but recorded zero Jev executions.

Before another A/B/C matrix, freeze a small external public-eval cohort:

~~~bash
bash scripts/agentic-jev/p2-freeze-external-cohort.sh
~~~

This downloads and pins the Inspect Evals source, then creates a 12-task
development-only cohort:

- six SWE-Lancer `swe_manager` tasks selected deterministically by ID from the
  pinned upstream CSV, without reading correct-proposal fields;
- six SWE-bench Verified Mini issues chosen for visible semantic ambiguity in
  public problem/discussion text.

The freeze does **not** run a model or pull the large task images.

The first execution is intentionally **C arm on the six SWE-Lancer manager tasks
only**. Those tasks directly present competing implementation proposals, so they
are the cleanest public Jev Choice stressor in the frozen cohort. The six frozen
SWE-bench IDs are held for later review rather than run automatically.

After the cohort is frozen, prepare the pinned external dependencies and run the
C-only scout:

~~~bash
bash scripts/agentic-jev/p2-prepare-external-evals.sh
bash scripts/agentic-jev/p2-run-external-c.sh
~~~

The runner executes one frozen SWE-Lancer manager sample at a time and stops after
six tasks, so each private Jev receipt stream maps unambiguously to one task ID.
Scoring is disabled in this uptake-only phase. Do not refreeze or requalify unless
the already-frozen Agentic Jev runtime itself changes.

Canonical design:
`docs/AGENTIC_JEV_EXTERNAL_EVAL_SCOUT.md`.


## Phase 3 — correct the agent-facing Jev skill treatment

The benchmark decision skill is derived from
`ngallodev-software/jev-decision-support@65b444965e48209860e353f2aa0e8d9dbe35d2ce`.
Its public evidence-first Choice/Noul/Score workflow is retained, while benchmark
live inference is restricted to the host-side `jev_system_one` bridge. Direct SDK
or HTTP fallback is intentionally prohibited so credentials stay host-only and
receipts remain authoritative.


The original upstream `typesafe-ai` skill is an integration/build skill and did
not teach the coding agent to use the available Jev bridge for its own bounded
decisions. Preserve the completed zero-call runs as evidence of that treatment.

The corrected additive treatment is `agentic-jev-decision-skill-v2`.

Freeze it:

~~~bash
bash scripts/agentic-jev/p3-freeze-decision-skill-v2.sh
~~~

Then qualify **skill activation** on a proposal-choice task that does not mention
Jev or TypeSafe:

~~~bash
bash scripts/agentic-jev/p3-qualify-decision-skill-v2.sh
~~~

Do not run the real manager gate unless this passes.

After a pass:

~~~bash
bash scripts/agentic-jev/p3-run-manager-v2.sh
~~~

Canonical design:
`docs/AGENTIC_JEV_DECISION_SKILL_V2.md`.
