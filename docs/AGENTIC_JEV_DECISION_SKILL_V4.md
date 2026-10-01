# Agentic Jev decision-support skill v4 source refresh

**Status:** SOURCE-SYNCHRONIZED / NOT YET A LIVE TREATMENT  
**Source:** `ngallodev-software/jev-decision-support@627e508fb8798f66c4bae180b432c30dbe44570e`

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

### Richer review context

For review/proposal decisions, project:

- verbatim requirement text when available;
- the diff/proposal plus unchanged code it depends on;
- verification results with explicit scope and omissions;
- any prior Jev answer plus the material changes that justify asking again.

This is directly relevant to the manager-trace audit: a semantic check should receive
the authority/evidence surface that the coding agent used, not only its paraphrased
conclusion.

### Validated batching

Related Choice, Noul, and Score questions should share one decision context and one
Jev call. The benchmark host bridge already validates typed question maps and records
the answer set, so the standalone helper implementation is not copied.

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
a decision at all. The next architecture question is therefore a provider-neutral
Agent-Workflow decision checkpoint/reconciliation gate, potentially implemented with
a graph runtime such as LangGraph.

v4 should be the semantic-guidance asset used by that future work when agent-directed
Jev remains appropriate. Registered consequential seams should be structurally
enforced by Agent-Workflow rather than depending on the coding agent to decide
whether independent evidence is needed.

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
