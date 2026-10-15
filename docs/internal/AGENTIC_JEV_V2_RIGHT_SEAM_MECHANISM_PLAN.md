# Agentic-Jev v2 right-seam mechanism plan

**Status:** exploratory design over already-observed v2 cohort; no fresh effectiveness tasks authorized  
**Source cohort:** `agentic-jev-swe-manager-v2` (30 observed paired tasks / 39 archived Jev calls)  
**Design rule:** **Jev at the right semantic seams, not more Jev.**

## Why this phase exists

The completed exact-request audit changed the mechanism diagnosis.

On the first Jev call for each v2 task, Jev selected the official correct proposal on
17/30 tasks (56.7%). Control finished 16/30 (53.3%) and treatment 15/30 (50.0%). Nine
first calls with `evidence_sufficient < 0.50` triggered more Luna investigation and a
second Jev request. All nine remained below 0.50, only one Jev Choice changed, and that
change moved from correct to incorrect. Final Jev Choice fell to 16/30.

The repeat path was also the expensive path. Two-call treatment tasks averaged roughly
+94k Luna tokens and +57 s versus control, compared with roughly +15k tokens and +15 s
for one-call tasks. The nine second Jev calls themselves consumed only about 1.6 s of
provider time. The observed loss is therefore primarily a workflow/composition problem,
not a provider-latency problem.

This phase must use the already-observed cohort for exploratory provider-only replay
and deterministic counterfactual composition. It must not consume fresh SWE-Lancer
manager tasks. Any treatment selected here requires a new versioned preregistration and
a fresh disjoint effectiveness cohort.

## Frozen source material

Mechanism replay starts from the exact first-call v2 semantic state for each of the 30
observed tasks. Gold/correct proposal is excluded from every provider request and from
all request construction. Gold is joined only after calls complete for analysis.

The original first call is the primary anchor. Second-call state may be analyzed as an
observed revision artifact, but no mechanism is allowed to silently substitute the
second call for the first-call signal.

For every replay preserve privately:

- source task/sample identity;
- exact v2 first-call state and question body;
- semantic-content hash;
- exact order-preserving dispatch-body hash;
- explicit requested model and resolved model;
- criteria/question order;
- provider request ID, usage, duration and full typed answers;
- mechanism ID/version and deterministic composition result.

## Mechanism questions

This phase answers four narrower questions before another effectiveness study.

1. **Granularity:** is `best_proposal` too broad a semantic judgment?
2. **Composition:** can code compose typed Jev evidence more faithfully than Luna's
   free-form reconciliation?
3. **Escalation:** should low evidence sufficiency route to review/escalation instead of
   same-agent investigation plus a second semantic call?
4. **Signal preservation:** can the first Jev selection remain visible and immutable
   even when the workflow decides not to act on it?

## Experiment M0 — exact first-call replay control

Replay the original first-call request exactly, including question and option order,
against an explicitly pinned requested model.

Purpose:

- establish replay variance separately from treatment changes;
- verify exact dispatch identity machinery;
- quantify how stable the 17/30 first-call result is under repeated provider sampling.

M0 is not a new treatment and cannot support a fresh effectiveness claim.

## Experiment M1 — descriptive criteria, same broad Choice

Keep the exact v2 state and broad `best_proposal` question, but replace opaque criteria
such as `Official task proposal 2` with criteria that explicitly point to the proposal
text already present in state, for example:

~~~text
proposal_2:
  Select when authoritative_task.proposals.proposal_2 best satisfies the task
  requirement and supplied repository/verification evidence relative to the other
  official proposals.
~~~

Keep proposal order fixed to the source request for the first comparison.

Question answered: was avoidable ID-to-state indirection degrading the broad Choice?

This is the smallest semantic-shape change and should be tested before inventing a more
complex decomposition.

## Experiment M2 — separate selection from sufficiency, compose in code

Remove `insufficient_evidence` from the proposal Choice. The Choice answers only:

> Which supplied official proposal is best supported relative to the other supplied
> proposals?

Retain a separate `evidence_sufficient` Noul over the same neutral state.

Deterministic composition must preserve both outputs:

~~~text
selection_signal = Jev proposal Choice           # never overwritten by sufficiency
sufficiency_signal = Jev evidence Noul

if sufficiency_signal >= routing_threshold:
    workflow_action = "candidate_selection"
else:
    workflow_action = "review_required"

candidate = selection_signal                     # retained in either branch
second_same-agent_jev_call = forbidden
~~~

The Noul is therefore a routing signal, not a correctness-confidence proxy and not a
request-rebuild trigger.

Exploratory analysis must sweep routing thresholds after calls are frozen rather than
pretending the v2 value `0.50` was calibrated. Report coverage and correctness among
acted-on cases at each threshold, plus all-case raw Choice correctness. Threshold
selection for any future live treatment must then be preregistered on a disjoint
cohort; do not optimize and claim on these 30 tasks.

## Experiment M3 — narrower per-proposal evidence judgment with deterministic ranking

Test one materially narrower semantic seam without multiplying provider calls.

Use one batched request over the same neutral state. For every official proposal ask a
parallel typed Score with identical semantics:

~~~text
support_for_<proposal_id>:
  How strongly do the authoritative requirement, repository evidence, and explicit
  verification scope support this proposal as an implementation choice?
~~~

All proposal Scores share the same bounded scale and wording. Code selects the highest
score. Ties within a preregistered epsilon produce `review_required`; code never asks
Jev to break its own tie in a second call.

This experiment deliberately decomposes **evaluation** from **selection**: Jev judges
bounded support for each candidate; deterministic code performs the relative ranking.
It is preferable to a many-call pairwise tournament because the research target is a
better seam, not increased invocation count.

Before live replay, qualify that the Score scale has an unambiguous common anchor and
that all proposal questions fit in one request without truncation. If the SDK/provider
contract cannot support a defensible common Score scale, stop M3 rather than silently
substituting another question type.

## Experiment M4 — escalation policy counterfactual, no new provider call

Using only already-recorded first-call v2 outputs, compare deterministic policies:

- **v2 observed:** low Noul -> same Luna investigates -> second Jev call -> Luna
  reconciles;
- **preserve-first:** always retain first Choice; low Noul -> `review_required`;
- **choice-only:** first Choice is candidate regardless of Noul;
- **abstention-sensitive:** explicit semantic abstention (where a mechanism supports
  it) -> `review_required`, otherwise retain candidate.

M4 requires no provider inference. It isolates orchestration policy from semantic model
quality and makes the cost of the observed retry loop explicit.

## Order-sensitivity subexperiment

Order is a mechanism variable, not a hidden nuisance.

For M1-M3, use a deterministic counterbalanced order schedule derived from
`sha256(mechanism_id + sample_id)`. Run both source order and one deterministic rotated
or reversed order where feasible. Preserve exact dispatch-body hashes separately from
canonical semantic-content hashes.

Report:

- top-choice/ranking flip rate;
- probability/score movement;
- correctness movement after gold join;
- whether composition outcome changes.

Do not average away a top-choice flip as mere decimal variance.

## Primary exploratory outputs

No single metric is sufficient. Produce a mechanism table with:

- raw first-call candidate correctness;
- candidate coverage (fraction not routed to review);
- selective correctness among candidate-selection cases;
- review-routing rate;
- change versus original first-call candidate;
- change versus observed final Jev candidate;
- order-flip rate;
- provider calls/task;
- provider tokens/task and duration/task;
- projected workflow calls avoided relative to the v2 retry path.

For every metric state that this is exploratory reuse of an observed cohort, not a
fresh causal estimate.

## Decision rule for the next fresh treatment

Do **not** select a mechanism merely because it has the highest post-hoc accuracy on
these 30 tasks.

A mechanism is eligible for fresh preregistration only if it satisfies all of:

1. semantic contract is narrower or composition is more explicit than v2;
2. no same-agent Noul-triggered retry loop;
3. first-call candidate remains auditable and is never silently overwritten;
4. deterministic code owns routing/composition;
5. no more than one Jev request is required in the normal decision path;
6. exact request order and dispatch identity are preserved;
7. exploratory performance is not materially worse without a compensating,
   explicitly stated coverage/review tradeoff;
8. the mechanism has a plausible workflow-level value proposition independent of
   this cohort's gold labels.

If M1 is competitive with more elaborate variants, prefer M1/M2-style simplicity over
M3. If no mechanism clears these conditions, the correct next step is to narrow or
remove this Jev seam rather than consume another fresh cohort.

## Repository ownership

- `agent-workflow-benchmark` owns replay execution, provider dispatch, evidence sealing,
  mechanism qualification, and publication preparation.
- `agent-workflow-comparative-eval` should receive new provider-neutral comparison
  fields only if the replay exposes a reusable metric/contract need; do not put
  Jev-specific mechanism policy there.
- Agent-Workflow owns any eventual production checkpoint/routing authority.
- Jev/TypeSafe remains a semantic evidence provider and never owns workflow action.
- The lab notebook records discoveries append-only; it must not rewrite the v2 result
  into a cleaner retrospective story.

## Immediate implementation sequence

1. Materialize a private replay manifest from the retained 30 first-call v2 requests.
2. Add exact order-preserving dispatch hashing before any replay.
3. Implement M0 and verify byte/structure-equivalent first-call replay construction.
4. Implement M1 and M2; run provider-only replay over the observed cohort.
5. Run M4 from existing evidence in parallel; it requires no provider calls.
6. Qualify M3's common Score semantics on already-observed tasks, then run it only if
   the qualification is defensible.
7. Freeze exploratory results and write an append-only mechanism finding.
8. Only then choose whether a fresh versioned treatment is warranted.

No fresh effectiveness cohort is authorized by this document.