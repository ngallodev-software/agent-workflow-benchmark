# Agentic Jev Decision-Skill v3

**Study identity:** `agentic-jev-decision-skill-v3`  
**Status:** DEVELOPMENT-ONLY / treatment refinement  
**Predecessor:** `agentic-jev-decision-skill-v2`

## Why v3 exists

v2 established two facts:

1. the adapted Jev skill can independently activate on a genuinely unresolved
   semantic trade-off;
2. the same treatment made zero Jev calls across six SWE-Lancer manager tasks.

Review of the pinned SWE-Lancer implementation showed that manager tasks are built
around an externally defined `correct_proposal_id`. The agent is expected to inspect
the repository and identify the objectively correct proposal.

That differs from the synthetic v2 activation fixture, where every option satisfied
the deterministic constraints and only a semantic trade-off remained.

Review also found that the benchmark v2 derivative narrowed the standalone public
skill more than intended. The public skill advertises:

- proposal/alternative judgment;
- evidence sufficiency;
- semantic risk.

The v2 benchmark gate allowed **no Jev call at all** once deterministic evidence
identified a tentative single answer. That suppresses evidence-sufficiency and risk
questions precisely when a complex repository task may have produced a likely
answer without proving that the evidence is complete.

v3 changes that policy without weakening deterministic authority.

## v3 policy

After deterministic inspection, classify the seam:

### Hard-resolved

If exact tests/specifications/invariants/user instructions resolve the decision and
no consequential semantic uncertainty remains, do not call Jev.

### Open choice

If multiple viable alternatives remain, use Choice.

### Tentative leader with residual semantic uncertainty

If one proposal leads but the remaining uncertainty concerns:

- whether the evidence is sufficient to finalize;
- qualitative implementation risk;
- reversibility;
- maintainability;
- review surface;
- migration consequences;

then use Noul and/or Score in a single bounded Jev request.

The Jev result does not override exact evidence.

This is the key v3 delta:

> deterministic evidence remains authoritative, but forming a tentative answer no
> longer automatically closes every semantic-support seam.

## Source

v3 remains derived from:

- `ngallodev-software/jev-decision-support`
- commit `65b444965e48209860e353f2aa0e8d9dbe35d2ce`
- `skills/jev-decision-support/SKILL.md`

Transport remains benchmark-specific and host-bridge-only through
`jev_system_one`.

## Lineage freeze

v3 freezes against the completed v2 evidence:

- passing v2 runtime/treatment lock;
- passing `semantic-tradeoff-v2` activation qualification;
- six-sample v2 manager run with zero Jev calls.

That makes the policy change explicit rather than rewriting v2.

Freeze:

~~~bash
bash scripts/agentic-jev/p4-freeze-decision-skill-v3.sh
~~~

## Qualification: second-order activation

v3 has a new qualification fixture designed to test the newly added pathway.

The fixture deliberately makes `proposal_2` deterministically required by an exact
compatibility test. However, it separately leaves two semantic questions unresolved:

- is the available evidence sufficient to finalize without more investigation?
- how much qualitative implementation risk does the shared-path change introduce?

The task prompt names neither Jev nor TypeSafe.

The same fixture is run with:

~~~text
control:
  v2 decision skill + live Jev

treatment:
  v3 decision skill + live Jev
~~~

The v3 qualification passes only when:

- control records zero Jev calls;
- treatment records exactly one successful Jev call;
- that call contains at least one Noul or Score primitive;
- the API key remains absent from the agent transcript.

Run:

~~~bash
bash scripts/agentic-jev/p4-qualify-decision-skill-v3.sh
~~~

## Real-task gate: two-manager canary

Do not immediately repeat all six manager tasks.

After v3 qualification passes, run only the first two IDs from the already-frozen
manager cohort:

~~~bash
bash scripts/agentic-jev/p4-run-manager-canary-v3.sh
~~~

The order is inherited from the frozen cohort; no post-hoc task selection is done.

The canary passes only if:

- both task executions complete without sample errors; and
- at least one authoritative host-side Jev receipt is recorded.

A zero-call canary is preserved and stops the experiment before the remaining four
manager tasks.

## Claim boundary

v3 remains an uptake experiment.

A passing qualification proves the newly added second-order pathway can activate.

A passing real-task canary shows that pathway generalizes to at least one public
SWE-Lancer manager task.

Neither establishes that Jev improves proposal-selection accuracy, cost, latency,
or software quality. Any effectiveness study must be separately designed and
scored.
