# Agentic Jev / Agent-Workflow — Fresh-Thread Handoff

**Date:** 2026-10-01  
**Purpose:** continue from the completed agent-directed Jev pilot and move into the provider-neutral Agent-Workflow decision-checkpoint / reconciliation architecture question.

## Read first

Treat these as authoritative before making implementation assumptions:

1. project-level Comparative Evaluation instructions;
2. this handoff;
3. current repository HEADs;
4. the frozen v2/v3 evidence and the private manager trace audit.

Do not reconstruct the experiment from memory and do not rewrite earlier evidence in place.

## Current repository state

| Repository | Branch | Relevant HEAD / identity |
| --- | --- | --- |
| `ngallodev-software/agent-workflow-benchmark` | `main` | Jev v4 source-sync merge `7213290587f57b635de711751b937d6e80e0e2d2` |
| `ngallodev-software/agent-workflow` | `master` | `c4679d7552f28d2f3d21e776804e6c3139542309` |
| `ngallodev-software/agent-workflow-comparative-eval` | `master` | `0d7510735958a00d1e12d3eb5277b5bb1964f6e9` |
| `ngallodev-software/jev-decision-support` | `main` | `5b43c3f1cd289361cf7715588cbc3871f2f6947f` |
| private `ngallodev-software/agent-workflow-lab-notebook` | `main` | read current HEAD; Jev history is additive and must not be rewritten |

Benchmark PRs just completed:

- PR #86 → merge `418c5020e9dc6ef7ea5365a1783568dc66781bd7`: added source-synchronized Jev decision-support v4.
- PR #87 → merge `7213290587f57b635de711751b937d6e80e0e2d2`: advanced v4 to the latest public skill source and its controlled context-sensitivity caveats.
- Exact PR #87 head `4069e7b88c60023610c7c0286e369b13cee7e629` passed unit tests, Agentic-Jev import, and Inspect import before merge.

## Architectural invariants

Do not blur repository ownership:

- Agent-Workflow owns deterministic application and lifecycle authority.
- Comparative-eval owns provider-neutral comparison contracts, metrics, pairing, statistics, and report semantics.
- Benchmark owns experimental execution, scoring, sealing, collection, and publication preparation.
- Benchmark-results owns sanitized public evidence.
- TypeSafe/Jev is a semantic evidence provider, not workflow authority.

The existing Agent-Workflow decision architecture already reflects this direction:

~~~text
StateProjector
  -> bounded QuestionSet
  -> TypeSafe/Jev Choice | Noul | Score
  -> normalized DecisionReceipt
  -> Agent-Workflow DecisionPolicy
  -> deterministic consumer
~~~

Current live Agent-Workflow semantic decisions remain routing-oriented; do not assume proposal-selection is already a production decision seam.

## Jev skill identities — do not conflate them

### Historical v2

The v2 skill is frozen from public source commit:

`65b444965e48209860e353f2aa0e8d9dbe35d2ce`

It produced observed qualification and manager evidence. Do not edit its asset.

### Historical v3

v3 was a separate treatment attempting to make second-order evidence-sufficiency / risk use more explicit.

Its qualification was non-discriminating: both v2 control and v3 treatment independently made one successful Jev request containing Noul + Score. Therefore v3 did not isolate a new behavior. Its real-task canary was retired.

Do not run `p4-run-manager-canary-v3.sh`.

### Current source-synchronized v4

v4 is **not a live experimental treatment**. It is the current benchmark-specific semantic-guidance asset for future work.

Paths:

~~~text
src/agent_workflow_benchmark/assets/agentic-jev-decision-v4/
  SOURCE.md
  jev-decision-support/
    SKILL.md
    agents/openai.yaml

src/agent_workflow_benchmark/benchmarking/
  agentic_jev_decision_v4.py

docs/AGENTIC_JEV_DECISION_SKILL_V4.md
~~~

Current source pin:

~~~text
repository: ngallodev-software/jev-decision-support
commit: d0ac1ef45d1b79b18b2905872c62cb9e68d961c7
source skill Git blob: ad6e00a2346ddf15009ad5119310cff3388ff8a2
source OpenAI metadata Git blob: ba931acbdbdd7e1f8327db63f93468e396672d14
source helper Git blob: bb28c18553cb9bebd3d4894e06ef587e8e04c47c
~~~

v4 intentionally keeps benchmark transport stricter than the public standalone skill:

- live inference is host-only through `jev_system_one`;
- `TYPESAFE_API_KEY` stays outside the coding-agent sandbox;
- no SDK install/import, direct HTTP call, local helper, or credential-search fallback in benchmark execution;
- host receipt streams are authoritative execution evidence;
- benchmark limits remain 16 questions, 64 KiB normalized state, 48 KiB normalized questions;
- Jev output remains evidence, not authority.

## Latest public-skill changes now integrated into v4

The source skill added and refined several pieces that matter to the next architecture:

1. For review/proposal judgments, include the requirement source verbatim when available.
2. Include the candidate diff/proposal plus unchanged code it depends on.
3. Include deterministic tool output verbatim with scope: what ran, results/counts/failures, and what was not exercised.
4. Keep the candidate agent's preferred answer, confidence, and verdict out of neutral Jev evidence.
5. Treat notes/summaries/verdicts from other agents as claims, not deterministic tool output.
6. Exclude prior Jev answers by default; include one only when the question is explicitly about change since that answer.
7. Label unavoidable agent-only observations with source and basis.
8. Isolate evaluation of an agent-authored proposal from unrelated semantic questions.
9. Batch only related Choice/Noul/Score questions that should share the same neutral primary-evidence context.
10. Treat every requested answer as decision evidence; do not silently ignore an inconvenient batch answer.
11. Treat close distributions as split evidence rather than collapsing a narrow plurality into certainty.
12. Project evidence to fit limits; do not silently truncate it.

The latest source also replaced an unsupported causal claim with a controlled result. In one pre-registered code-review ablation using `jev-1.13.0` and five calls per arm, richer context materially sharpened the distribution: reported spec-fit moved from about 0.35 to 0.89 and P(needs_changes) from about 0.49 to 0.18. Replacing a type-checker-failing commit with the fixed commit changed little.

Carry the caveats, not just the headline:

- sharper Jev evidence is **not correctness**;
- defects absent from the projected evidence can remain invisible;
- deterministic tests/type checking/linters remain separate authority-bearing evidence;
- JSON key/order changes alone shifted probabilities by about 0.1 and flipped a top choice in that controlled case;
- therefore freeze serialization/question ordering for comparative calls and do not over-read small decimal differences.

## Completed agent-directed Jev history

### Original pilot

The original 24-task C arm completed all tasks with the TypeSafe skill and a live qualified Jev tool available, but recorded zero Jev calls.

That original skill was later diagnosed as primarily a product-integration/build skill rather than an agent-self-use decision skill.

### External manager scout

Six frozen SWE-Lancer manager tasks completed with zero Jev calls.

### v2 activation qualification

The first v2 activation fixture was invalid because deterministic facts made one proposal uniquely correct while the skill correctly said not to delegate deterministically resolved decisions. Preserve that failed attempt.

The corrected hash-bound `semantic-tradeoff-v2` fixture passed:

~~~text
control Jev calls:   0
v2 treatment calls:  1
activation_lift_observed: true
protocol SHA-256:
a797420a607f0cc7801481991da2fd730dfc9d0ba7526db5337e22c5b20c54b8
~~~

This proved skill-mediated synthetic activation, not effectiveness.

### Six-task v2 manager run

The same v2 treatment then completed all six frozen SWE-Lancer manager tasks:

~~~text
samples: 6
success: 6
errors: 0
Jev calls: 0
~~~

Private evidence root:

~~~text
~/.local/share/agent-workflow/agentic-jev-pilot-v1/
  decision-skill-v2/manager-run/
~~~

Derived private audit:

~~~text
~/.local/share/agent-workflow/agentic-jev-pilot-v1/
  decision-skill-v2/manager-run-audit/audit.json
~~~

The audit hash-binds the source manifest and Inspect logs, includes observable assistant/tool evidence, and does not export raw reasoning-block contents.

### v3 qualification

A synthetic second-order fixture was intended to prove a new Noul/Score pathway after a tentative leader existed.

Instead:

~~~text
v2 control:
  Jev calls: 1
  successful: 1
  primitives: Noul + Score

v3 treatment:
  Jev calls: 1
  successful: 1
  primitives: Noul + Score
~~~

Therefore v2 already supported the second-order behavior; v3 was redundant.

## Manager trace audit — key finding

Post-hoc, the six observed proposal selections were compared with the public SWE-Lancer gold proposal IDs. This was an exploratory diagnostic, **not preregistered effectiveness scoring**.

Observed:

~~~text
samples: 6
Jev calls: 0
gold-correct selections: 3
gold-wrong selections: 3
observed accuracy: 50%
~~~

Selections:

| task | Luna | public gold | result |
| --- | ---: | ---: | --- |
| 27538-manager-0 | 2 | 1 | wrong |
| 18207-manager-0 | 1 | 1 | correct |
| 17387-manager-0 | 8 | 8 | correct |
| 17073-manager-0 | 4 | 4 | correct |
| 16946-manager-0 | 5 | 0 | wrong |
| 19232-manager-0 | 3 | 4 | wrong |

The zero-use result cannot be explained simply by saying repository evidence made every manager task deterministic.

Examples:

- `16946-manager-0`: Luna found the nested-Pressable mechanism but still had an architectural-scope choice among plausible remedies; it selected the wrong gold proposal without Jev.
- `19232-manager-0`: Luna found the style-order mechanism but had to reconcile original issue expectations against later proposal-level/new-requirement intent; it selected the wrong gold proposal without Jev.
- even correct cases used comparative language such as “closest match” or “best matches the established pattern,” which is semantic judgment rather than mechanical proof.

Lab-notebook records include:

- `events/2026-09-30-agentic-jev-manager-trace-audit-self-gating.md`
- commit `59d354174e98b9f71ddeae0f72952d96b3b15252`
- timeline commit `627ce7271f9255365c9fd3c6384c799dd024afbf`

## Current interpretation: optional self-gating is the failure mode

The most useful current hypothesis is:

> optional semantic assistance has a bootstrap problem: the same agent whose judgment may be overconfident decides whether it needs an independent semantic check.

The evidence now supports all of these:

~~~text
Jev bridge works                         yes
agent-facing skill can activate          yes
open Choice can activate                 yes
Noul/Score second-order use can activate yes
six real manager tasks                   zero calls
three of those selections                gold-wrong
~~~

Stop making the skill progressively more eager.

The next experiment/architecture must separate:

1. spontaneous optional Jev uptake; from
2. decision quality when an independent semantic checkpoint is structurally required.

## Architecture direction discussed immediately before this handoff

Do **not** build a Jev-specific production agent harness by default.

The stronger direction is an Agent-Workflow-owned, provider-neutral semantic decision checkpoint:

~~~text
coding agent investigates
        |
        v
structured DecisionDraft
  - bounded candidates
  - tentative selection
  - evidence refs
        |
        v
Agent-Workflow checkpoint
  - validates/project evidence
  - calls configured semantic provider
        |
        v
Jev / future provider evidence
        |
        v
Agent-Workflow DecisionPolicy
        |
        +-- agreement ---------> continue
        |
        +-- disagreement ------> mandatory reconciliation
        |
        +-- uncertainty -------> more evidence / reviewer / human
        |
        +-- provider failure --> defined deterministic fallback
        |
        v
DecisionResolution receipt / applied_result
        |
        v
implementation/finalization allowed
~~~

The important property is structural:

**Luna may disagree with Jev, but Luna cannot silently ignore a registered semantic disagreement.**

Jev should not become authoritative. Instead, disagreement must produce a structured reconciliation artifact with evidence references, or route to independent review/human escalation according to consequence/policy.

Possible reconciliation fields:

~~~json
{
  "decision_id": "implementation.proposal_selection",
  "initial_agent_choice": "proposal_5",
  "semantic_candidate": "proposal_0",
  "resolved_choice": "proposal_5",
  "disposition": "reject_semantic_candidate",
  "basis": "deterministic_authority",
  "evidence_refs": ["..."]
}
~~~

Agent-Workflow validates whether that disposition is permitted and whether the required evidence exists before allowing the workflow to advance.

## LangGraph question for the next thread

The user explicitly asked whether this is a good opportunity to use LangGraph or another existing framework.

Current provisional direction:

- LangGraph is a plausible **inner agent-execution state machine**, especially for conditional edges, reconciliation loops, and pause/resume/interrupt semantics.
- It should **not** replace Agent-Workflow's canonical lifecycle, decision policy, receipts, or evidence authority.
- Avoid dual sources of truth. If LangGraph is used, its checkpoint is execution/restart convenience; Agent-Workflow state/receipts remain canonical.
- Temporal is worth evaluating only if the goal expands toward distributed, multi-day, crash-resilient workflow infrastructure; it is likely larger than the immediate problem.
- OpenAI Agents SDK may be useful as an executor backend, but should not become the architectural center of a provider-neutral study.

Do not adopt LangGraph merely to add it to the stack. The next thread should inspect current Agent-Workflow execution/lifecycle code and establish whether LangGraph removes meaningful custom orchestration machinery without duplicating authority.

## Recommended next-thread work

1. Read current `agent-workflow@master`, especially:
   - `src/agent_workflow/decisions.py`
   - decision/lifecycle receipts and schemas
   - workflow snapshot/run/node-result machinery
   - orchestrator and agent-run control paths
   - `DECISION_MODES.md`
   - `TYPESAFE_ARCHITECTURE_ALIGNMENT.md`
   - `docs/SEMANTIC_DECISION_AUDIT.md`
2. Map one concrete new seam:
   `implementation.proposal_selection/v1`.
3. Specify the minimum provider-neutral contracts:
   - DecisionDraft
   - StateProjector / evidence references
   - SemanticEvidence
   - reconciliation requirement
   - DecisionResolution / applied result
   - lifecycle gate.
4. Evaluate LangGraph against that exact state machine:
   - what execution mechanics it replaces;
   - what state it would own;
   - what Agent-Workflow must continue to own;
   - persistence/restart behavior;
   - provider neutrality;
   - testability and evidence capture.
5. Produce an ADR/design before broad integration.
6. If the fit is strong, prototype exactly one checkpoint seam on a feature branch.
7. Use the six known SWE-Lancer manager tasks only as **mechanism-development/replay** cases.
8. For any effectiveness claim, freeze a new disjoint manager cohort with scoring and paired analysis specified before outcomes are observed.

## Evidence requirements for the next experiment

Capture at minimum:

- initial agent candidate before semantic evidence;
- bounded options actually considered;
- evidence refs / projected state hash;
- provenance classes for projected fields (primary evidence, deterministic tool output, agent observation, agent-authored proposal);
- proof that the candidate agent's preferred answer was excluded from neutral provider state;
- stable serialization/question ordering identity for comparative calls;
- Jev request identity and complete typed distribution;
- agreement/disagreement;
- reconciliation action and rationale;
- final applied decision;
- deterministic authority invoked, if any;
- review/human escalation;
- latency, token, and cost overhead;
- final correctness against independent ground truth;
- observable agent messages/tool sequence relevant to the decision.

Do not claim access to hidden chain-of-thought. Preserve observable decision evidence.

## Do not do these things

- Do not rerun or overwrite the frozen v2 manager run.
- Do not run the retired v3 manager canary.
- Do not mutate v2/v3 skill assets.
- Do not treat v4 as a live treatment merely because it exists.
- Do not use the six known gold labels to tune a future effectiveness cohort.
- Do not let Jev directly own workflow/lifecycle authority.
- Do not let a coding agent silently discard registered semantic disagreement.
- Do not create two canonical state stores if testing LangGraph.
- Do not collapse close semantic distributions into certainty.
- Do not feed the candidate agent's preferred answer into neutral Jev evidence.
- Do not mix an agent-authored proposal into unrelated semantic batches.
- Do not infer correctness from Jev confidence alone.

## Suggested opening instruction for the next thread

> Read the Comparative Evaluation project instructions and this handoff. Verify the current GitHub HEADs before assuming anything. Continue from the Agentic-Jev manager trace audit and v4 source-synchronized skill state. The immediate task is to design the provider-neutral Agent-Workflow semantic decision checkpoint/reconciliation architecture and evaluate whether LangGraph should provide the inner execution state machine without displacing Agent-Workflow's canonical lifecycle/receipt authority. Do not rerun the old Jev pilot or modify frozen v2/v3 evidence. Start by inspecting the current Agent-Workflow decision and lifecycle implementation, then produce the narrow architecture/ADR and identify the first prototype seam.
