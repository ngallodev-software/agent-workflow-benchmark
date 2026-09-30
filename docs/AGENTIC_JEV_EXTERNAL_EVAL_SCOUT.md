# Agentic Jev External-Eval Uptake Scout

**Study identity:** `agentic-jev-external-eval-scout-v1`  
**Status:** DEVELOPMENT-ONLY / source freeze before execution  
**Predecessor:** `agentic-jev-pilot-v1`

## Why this exists

The first 24 × 3 Agentic-Jev pilot completed all 72 coding-agent executions, but
the C arm made zero Jev calls.

That is useful uptake evidence, but the synthetic tasks frequently supplied a
strong deterministic repository answer. A second development-only scout should
therefore test the same optional Jev affordance on established public evaluations
with stronger semantic-decision pressure before spending on another full A/B/C
matrix.

This scout is **not** a retry of the first pilot and does not rewrite it.

## Public upstream sources

The source catalogue is frozen to:

- Inspect Evals repository: `UKGovernmentBEIS/inspect_evals`
- commit: `b49df6bc9e30b2d24571084bc710b9439b9ffa77`
- SWE-bench Verified Mini dataset:
  `MariusHobbhahn/swe-bench-verified-mini`
- SWE-bench Mini revision:
  `b316c349947c29963fce3f4a65967c9807a4b673`

Inspect Evals exposes SWE-bench Verified Mini as a 50-task smaller verified
SWE-bench cohort and SWE-Lancer as a public software-engineering evaluation with
an explicit `swe_manager` variant.

## Two complementary cohorts

### 1. SWE-Lancer manager Choice pressure

SWE-Lancer manager tasks require the agent to select the correct implementation
proposal from a set of candidates.

That shape maps naturally to a bounded Jev Choice judgment without forcing the
agent to use Jev.

Six manager tasks are selected from the pinned upstream CSV by a deterministic
hash of `question_id`.

The selector reads only:

- `question_id`
- `variant`
- `set`
- `title`

It does not use:

- `manager_data`;
- the correct proposal ID;
- scores/outcomes;
- proposal correctness metadata.

This cohort therefore does not hand-pick manager tasks by answer.

### 2. SWE-bench semantic-ambiguity coding tasks

Six SWE-bench Verified Mini tasks were selected during exploratory source
scouting because their public problem/discussion text exposes a plausible semantic
decision seam:

| Instance | Jev seam | Why it is useful |
| --- | --- | --- |
| `django__django-12273` | behavior intent | Discussion explicitly questions whether the behavior is a bug and what reset behavior is intended. |
| `django__django-12308` | implementation strategy | Discussion contrasts brittle special-casing with a broader type boundary. |
| `django__django-12406` | interaction policy | Correct behavior depends on the UI semantics of a blank option for required radio input. |
| `django__django-9296` | feature value | Maintainers weigh expected Python behavior against whether the feature is common enough to add. |
| `sphinx-doc__sphinx-10323` | composition semantics | The issue discusses how dedent should compose with prepend/append content. |
| `sphinx-doc__sphinx-8551` | ambiguity resolution | The issue balances false ambiguity warnings against silently resolving the wrong symbol. |

This manual selection is **development-only**, not blinded or confirmatory. The
public dataset viewer exposes gold patch/test columns adjacent to issue text, even
though the selection rationale intentionally uses only problem/discussion
semantics. Any later confirmatory study needs a fresh precommitted selection process.

## First execution gate: C arm on SWE-Lancer manager only

Do not immediately run the full 12-task external cohort or an A/B/C matrix.

The first live gate is only the six deterministically selected SWE-Lancer manager
tasks:

```text
Luna/high + frozen TypeSafe skill + live Jev
6 SWE-Lancer manager proposal-selection tasks
```

These tasks are the cleanest Jev stress surface in the frozen cohort because the
agent itself sees competing implementation proposals and must select among them.

The question is:

> Does Luna independently invoke a successfully qualified Jev primitive when the
> task directly requires semantic selection among competing implementation proposals?

The six SWE-bench IDs remain frozen as a possible second gate, but they are **not
authorized for execution yet**. During runner review we confirmed that some of the
discussion-based ambiguity used to motivate their selection lives in dataset
metadata/hints rather than the standard agent-visible SWE-bench problem statement.
Their treatment should be reconsidered after the manager result instead of silently
treating them as equivalent evidence.

### Stop after C

After the C-only run, inspect:

- Jev call count;
- task IDs at which Jev was called;
- primitive choice;
- successful/contract-failure/service-failure receipts;
- state/question shape;
- immediate action after the answer;
- whether a semantic decision was actually at issue.

Do not select a comparative winner or make an effectiveness claim.

If calls remain zero, the evidence increasingly favors the interpretation that
optional agent-directed Jev is not naturally entered under this coding-agent
instrument/skill/tool affordance.

If calls become nonzero, freeze the observed seam taxonomy before designing a
new comparative outcome study.

## Freeze the external cohort

After pulling the benchmark branch containing this study:

```bash
cd /path/to/agent-workflow-benchmark
bash scripts/agentic-jev/p2-freeze-external-cohort.sh
```

This:

1. downloads the exact pinned Inspect Evals source;
2. verifies its Git commit;
3. reads the packaged SWE-Lancer CSV without answer-based selection;
4. deterministically selects six manager task IDs;
5. binds the completed zero-call pilot as lineage;
6. writes a frozen `cohort.json`.

It does **not** run a model or download large task Docker images.

## Prepare the pinned upstream eval dependencies

The external runner imports the frozen Inspect Evals checkout directly, but its
SWE-bench and SWE-Lancer dependencies must be present in the Agent-Workflow Python
environment.

Run:

~~~bash
bash scripts/agentic-jev/p2-prepare-external-evals.sh
~~~

The preparation command installs the pinned checkout's `swe_bench` and
`swe_lancer` extras while explicitly holding:

- `inspect-ai==0.3.268`;
- `inspect-swe==0.2.71`;
- `typesafe-sdk==0.6.0`.

It then reloads the existing Agentic-Jev runtime lock. Preparation fails if the
environment no longer satisfies the already-qualified runtime identity.

**Do not refreeze or requalify merely because external eval dependencies were
installed.** The qualified Jev implementation is unchanged.

## Run the C-only external scout

After preparation:

~~~bash
bash scripts/agentic-jev/p2-run-external-c.sh
~~~

The runner:

1. verifies the exact Inspect Evals Git commit and frozen SWE-Lancer CSV hash;
2. verifies the SWE-bench Mini revision recorded by the cohort;
3. verifies lineage to the completed 24-sample/zero-call C arm;
4. reloads the existing passing runtime lock and qualification;
5. runs exactly the six frozen SWE-Lancer manager IDs with **C-skill-plus-jev only**;
6. stops before the SWE-bench half of the frozen cohort;
7. disables scoring because this phase measures uptake, not effectiveness;
8. gives each sample its own private Jev receipt file and Inspect log;
9. writes one `sample-result.json` after each completed sample;
10. writes `c-run-manager/run-manifest.json` only after all six attempts complete.

The per-sample execution is deliberate. The frozen Jev receipt contract does not
carry an Inspect sample ID, so one receipt stream per task provides an unambiguous
mapping from any Jev invocation to the exact public eval sample without modifying
the already-qualified host tool.

The output root is fail-closed. A partial attempt must be preserved and diagnosed;
do not rerun into the same `c-run-manager` directory.

## Claim boundary

This is a development-only uptake stress test.

It cannot establish that Jev improves or degrades software-engineering quality.
Its immediate purpose is only to determine whether a stronger public task surface
produces actual live-Jev treatment exposure.
