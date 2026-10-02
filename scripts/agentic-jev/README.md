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

The first protocol-v1 activation attempt is intentionally preserved under
`activation-qualification/`. Its fixture accidentally made one proposal
deterministically correct, conflicting with the skill's evidence-first rule.

The current command writes a separately versioned
`activation-qualification-v2/` result using a fixture where every proposal
satisfies deterministic constraints and the remaining choice is genuinely semantic.
The manager runner accepts only this protocol-v2 qualification.

Do not run the real manager gate unless protocol v2 passes.

After a pass:

~~~bash
bash scripts/agentic-jev/p3-run-manager-v2.sh
~~~

Canonical design:
`docs/AGENTIC_JEV_DECISION_SKILL_V2.md`.


## Phase 4 — second-order Jev decision support

The v2 skill activated on a synthetic unresolved trade-off but made zero Jev calls
across the six frozen SWE-Lancer manager tasks.

Pinned SWE-Lancer source shows manager tasks have an externally defined correct
proposal. v3 therefore restores the standalone skill's evidence-sufficiency and
semantic-risk pathways while retaining deterministic authority.

Freeze v3 against the completed v2 evidence:

~~~bash
bash scripts/agentic-jev/p4-freeze-decision-skill-v3.sh
~~~

Qualify the proposed **tentative leader / second-order judgment** pathway:

~~~bash
bash scripts/agentic-jev/p4-qualify-decision-skill-v3.sh
~~~

The observed qualification was non-discriminating: both v2 control and v3 treatment
made exactly one successful Jev call containing Noul + Score. Therefore v3 did not
isolate a new treatment behavior and the manager canary is retired.

Do not run `p4-run-manager-canary-v3.sh`.

Instead audit the immutable six-task v2 manager traces:

~~~bash
bash scripts/agentic-jev/p4-audit-v2-manager-traces.sh
~~~

The audit is read-only, hash-binds the source manifest and each Inspect log, exports
observable assistant/tool evidence, and records only the **count** of reasoning
blocks rather than their content.

Canonical design:
`docs/AGENTIC_JEV_DECISION_SKILL_V3.md`.


## Phase 5 — source-synchronize the benchmark Jev skill

The standalone `ngallodev-software/jev-decision-support` skill advanced at
`d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`.

Do not edit the frozen v2/v3 skill assets. Their exact content is part of already
observed experimental evidence.

The new benchmark derivative is:

~~~text
src/agent_workflow_benchmark/assets/
  agentic-jev-decision-v4/
    jev-decision-support/
      SKILL.md
      agents/openai.yaml
    SOURCE.md
~~~

v4 carries forward the source update's evidence-quality guidance:

- verbatim requirement text when available;
- candidate diff/artifact plus unchanged dependent code;
- deterministic tool output verbatim with explicit scope and omissions;
- keep the candidate agent's preferred answer/confidence out of neutral evidence;
- treat other-agent notes/verdicts as claims rather than tool output;
- exclude prior Jev answers by default to avoid anchoring;
- label unavoidable agent-only observations with source and basis;
- isolate agent-authored proposal evaluation from unrelated batched judgments;
- one validated batch only for related questions sharing neutral primary evidence;
- close distributions treated as split evidence;
- project evidence to fit limits rather than silently truncating it;
- retain deterministic verification because sharper Jev evidence is not correctness;
- keep serialized context/question ordering stable when comparing calls.

Benchmark execution remains stricter than the standalone skill: the direct SDK helper,
isolated `uv` runtime, direct HTTP fallback, and sandbox credential acquisition are
not copied. Live benchmark inference remains host-only through `jev_system_one`.

The standalone helper's rounded-distribution fix does not require a benchmark bridge
implementation change because the host bridge does not enforce the former strict
sum-to-one tolerance; regression coverage preserves acceptance of a live-like 0.99
probability sum.

v4 is **not yet a live treatment**. Do not infer a new qualification or run simply
because the asset exists. The next design step is the provider-neutral
Agent-Workflow decision-checkpoint/reconciliation architecture surfaced by the
manager trace audit.

Canonical design:
`docs/AGENTIC_JEV_DECISION_SKILL_V4.md`.


## Phase 6 — current GPT-6 model context/rationale qualification

The source-synchronized v4 skill is byte/provenance current with
`ngallodev-software/jev-decision-support@d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`.
Do not rewrite frozen v2/v3 assets.

Use the additive current-model qualification to verify three things on the current
coding-agent generation:

1. the installed decision-support skill produces one successful host-side Jev call;
2. the private host receipt contains fixture-complete primary context: verbatim
   requirement, both candidate artifacts, unchanged dependent code, deterministic
   verification output, and explicit verification omissions/scope;
3. the agent returns a bounded visible decision record containing justification,
   evidence refs, the decisive trade-off, semantic-evidence reconciliation, and
   remaining uncertainty.

The qualification never requires or exports hidden chain-of-thought.

Run Luna:

~~~bash
bash scripts/agentic-jev/p6-qualify-current-model.sh
~~~

Run GPT-6.1 Sol:

~~~bash
AGENTIC_JEV_CURRENT_MODEL='openai-api/codex-lb/gpt-6.1-sol' \
  AGENTIC_JEV_CURRENT_QUAL_ROOT="$AGENTIC_JEV_ROOT/current-model-qualification/gpt-6.1-sol" \
  bash scripts/agentic-jev/p6-qualify-current-model.sh
~~~

The prompt does not name Jev or TypeSafe. A pass is qualification evidence only;
it is not a correctness or treatment-effect claim.

Canonical design:
`docs/AGENTIC_JEV_CURRENT_MODEL_QUALIFICATION.md`.


## Phase 7 — preregistered paired SWE-Lancer manager effectiveness study

Phase 6 established that current GPT-6 Luna can activate the source-synchronized
Jev decision skill, send fixture-complete neutral context, and retain a bounded
visible justification. Phase 7 asks the distinct task-outcome question.

The study uses the official pinned Inspect Evals `swe_lancer(task_variant="swe_manager")`
task and official scorer rather than recreating dataset, sandbox, or correctness
logic locally.

The fixed 30-task cohort is selected deterministically from official manager sample
IDs while reading only `question_id`, `variant`, `set`, and `title`. Every
previously observed Agentic-Jev manager task is excluded from the prior frozen
cohort manifest before selection. Correct-proposal fields are not used to choose
the cohort.

The paired arms isolate live Jev availability:

~~~text
control    GPT-6 Luna/high + current Jev decision skill, no live Jev bridge
treatment  identical model/skill + host-side live Jev bridge
~~~

Both arms must leave the official `manager_decisions.json` plus a bounded visible
decision record with justification, evidence refs, decisive trade-off,
semantic-evidence reconciliation, and remaining uncertainty. Hidden chain-of-thought
is not requested or exported.

Freeze, prepare, then run:

~~~bash
bash scripts/agentic-jev/p7-freeze-swe-manager-study.sh
bash scripts/agentic-jev/p7-prepare-swe-manager-study.sh
bash scripts/agentic-jev/p7-run-swe-manager-paired.sh
~~~

The primary analysis is intent-to-treat for **live Jev availability**. Treatment
tasks where Luna does not call Jev stay in the denominator; called-only subsets are
descriptive because invocation is agent-selected. Official Inspect scoring remains
the correctness oracle.

Before the first task, the runner now writes a validated `run-start.json` that
binds the cohort, pinned source/scorer, benchmark git/source hashes, package
versions, and coding-agent/Jev request runtime. Phase 7 receipts are labeled with
the Phase 7 study ID, resolved Jev model identities are retained from successful
receipts, and structured Inspect usage is preserved for paired overhead reporting.
These pre-run evidence changes do not alter study treatment or correctness semantics.

Canonical design:
`docs/AGENTIC_JEV_SWE_MANAGER_V1.md`.
