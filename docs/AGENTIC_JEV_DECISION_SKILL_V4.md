# Agentic Jev decision-support skill v4 source refresh

**Status:** SOURCE-SYNCHRONIZED / NOT YET A LIVE TREATMENT  
**Source:** `ngallodev-software/jev-decision-support@d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`

## Why this is v4 instead of an edit to v2/v3

The v2 and v3 benchmark skill assets have already participated in observed
experiments. They are frozen evidence identities and must not be rewritten after
outcomes are known.

v4 is therefore a new derivative containing the current standalone skill guidance.
It is available for the next benchmark/harness design but has no live treatment,
qualification, cohort, or effectiveness claim yet.

## Integrated upstream changes

The source update added four useful behaviors that are now present in the benchmark
derivative.

### Richer review context, with evidence provenance

For review/proposal decisions, project:

- verbatim requirement text when available;
- the diff/artifact plus unchanged code it depends on;
- deterministic tool output verbatim with explicit scope and omissions.

Do not put the coding agent's preferred answer, confidence, or verdict into neutral
provider context. Treat other-agent notes, summaries, and handoffs as claims rather
than tool output. Exclude prior Jev answers by default because they can anchor the
next call. If an agent-only observation must be included, label its source and basis.

When the coding agent's own proposal is what Jev is judging, mark it explicitly and
evaluate it in a request isolated from unrelated semantic questions.

This is directly relevant to the manager-trace audit and the next checkpoint design:
the semantic provider should receive independently projected primary evidence rather
than a state already colored by the candidate agent's conclusion.

### Controlled evidence-contamination findings

The latest public skill adds live-tested evidence-isolation guidance. In the reported
`jev-1.13.0` review case:

- an unlabeled sentence asserting a serious defect moved a correct commit from
  P(needs_changes) 0.19 to 0.87;
- a real type-checker failure moved P(needs_changes) from 0.21 to 0.98;
- a confident agent assertion that the type-checker failure was a false positive
  barely moved that deterministic signal;
- labeling an agent-only false claim reduced its effect by about two-thirds but did
  not eliminate it;
- a prior Jev answer anchored a later judgment;
- adding an agent-authored proposal to a batch shifted unrelated questions.

These are not universal performance claims, but they are sufficient to require
provenance-aware context construction in the benchmark.

### Controlled context-sensitivity caveat

The latest source narrows the earlier generic "rich context is better" claim to a
controlled result. In one pre-registered code-review ablation using `jev-1.13.0`
with five calls per arm, richer context raised spec-fit from about 0.35 to 0.89 and
reduced P(needs_changes) from about 0.49 to 0.18. Replacing a type-checker-failing
commit with its fixed version changed little.

The benchmark derivative carries the two important caveats forward:

- sharper semantic distributions are not correctness; defects absent from the
  projected evidence remain invisible, so deterministic checks still run outside
  Jev and their scoped results should be included in state;
- serialization order matters enough to affect probabilities and even a top choice
  in that controlled case, so comparative calls must keep context/question ordering
  stable and should not over-interpret small decimal differences.

### Validated, isolated batching

Related Choice, Noul, and Score questions may share one request only when they should
share the same neutral primary-evidence context. Do not batch an agent-authored
proposal evaluation with unrelated questions. The benchmark host bridge already
validates typed question maps and records the answer set, so the standalone helper
implementation is not copied.

### Rounded probability distributions

The standalone helper fixed a real validation bug: the API emits two-decimal
probabilities, so a valid distribution can sum to 0.99. The standalone helper now
uses a per-option tolerance.

The benchmark host bridge never applied the former strict sum-to-one check; it
normalizes typed SDK answers and preserves returned probabilities. A benchmark
regression test explicitly covers a 0.99-summing distribution so this remains true.

### Split distributions remain uncertainty

A close distribution such as 0.52 versus 0.42 is recorded as split evidence, not
collapsed into a strong decision merely because one label wins.

### Evidence projection, not silent truncation

The standalone helper introduced a 64 KiB local request ceiling. The benchmark has
its own host validator and keeps those limits authoritative:

- 16 questions;
- 64 KiB normalized state;
- 48 KiB normalized questions.

The transferable rule is to project relevant evidence to fit the contract rather
than silently truncate it.

## Benchmark-only boundaries retained

The standalone skill now recommends an isolated `uv` runtime for direct SDK use.
That is deliberately **not** part of this benchmark derivative.

For benchmark execution:

- only the host-side `jev_system_one` bridge may perform live inference;
- `TYPESAFE_API_KEY` remains host-only;
- the coding-agent sandbox does not install/import `typesafe-sdk`;
- no direct HTTP or local-helper fallback is allowed;
- host receipts remain authoritative execution evidence;
- Jev remains evidence rather than workflow authority.

## Relationship to the manager self-gating result

v4 does not attempt to solve the manager zero-uptake result by making the skill more
aggressive.

The six-task trace audit showed that optional invocation can fail before Jev receives
a decision at all. Agent-Workflow DEC-010 has now resolved the next architecture
step as a provider-neutral semantic checkpoint/reconciliation gate owned by
Agent-Workflow.

LangGraph and Temporal are deliberately deferred for this seam because their durable
state/replay responsibilities would duplicate authority Agent-Workflow already owns.
The current mechanism prototype keeps Agent-Workflow snapshots, journals, receipts,
review, and acceptance authoritative while Jev remains bounded semantic evidence.

v4 remains the current semantic-guidance asset. The additive current-model
qualification in `AGENTIC_JEV_CURRENT_MODEL_QUALIFICATION.md` uses v4 unchanged to
verify live Jev activation, fixture-complete context projection, and a bounded
visible agent justification on GPT-6 Luna or GPT-6.1 Sol. Registered consequential
seams should still be structurally enforced by Agent-Workflow rather than depending
on the coding agent to decide whether independent evidence is needed.

## Programmatic identity

Use:

~~~python
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v4 import (
    decision_skill_path,
    decision_skill_sha256,
    decision_skill_interface_sha256,
    source_manifest,
)
~~~

No runtime or qualification should infer that v4 is active merely because these
assets exist.
