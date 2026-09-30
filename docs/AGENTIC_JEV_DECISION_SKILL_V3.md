# Agentic Jev Decision-Skill v3

**Study identity:** `agentic-jev-decision-skill-v3`  
**Status:** DEVELOPMENT-ONLY / NON-DISCRIMINATING QUALIFICATION / CANARY RETIRED  
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

## Qualification outcome: v3 did not isolate a new behavior

The first v3 activation qualification completed cleanly but failed the intended
discrimination predicate:

~~~text
v2 control:
  Jev calls: 1
  successful calls: 1
  primitives: Noul + Score

v3 treatment:
  Jev calls: 1
  successful calls: 1
  primitives: Noul + Score
~~~

Both arms preserved credential isolation.

This means the v2 control already performed the exact second-order evidence-
sufficiency / semantic-risk behavior that v3 was designed to add. The v3 fixture
therefore does **not** demonstrate a treatment delta.

Consequently:

- v3 is not an authorized successor treatment;
- the two-task manager canary is retired;
- do not modify the v2 skill again based on this qualification;
- the next step is a read-only audit of the six existing v2 manager traces.

The six manager zero-call result now carries a different interpretation: the v2
skill can use Jev for second-order Noul/Score judgments, but did not perceive such a
semantic seam in those six real tasks after repository inspection.

Run the trace audit:

~~~bash
bash scripts/agentic-jev/p4-audit-v2-manager-traces.sh
~~~

The audit derives a private JSON artifact from the immutable six-task manager run.
It includes observable assistant text, tool calls/results, selected proposal where
recoverable, and reasoning-block counts. It does **not** export raw reasoning-block
content.

## Real-task gate: two-manager canary

Do not immediately repeat all six manager tasks.

This gate is retired because the v3 synthetic qualification was non-discriminating:
the v2 control already made the same successful Noul+Score Jev call as v3.

Do not run `p4-run-manager-canary-v3.sh`. Audit the existing v2 manager traces
instead.

## Claim boundary

v3 remains an uptake experiment.

A passing qualification proves the newly added second-order pathway can activate.

A passing real-task canary shows that pathway generalizes to at least one public
SWE-Lancer manager task.

Neither establishes that Jev improves proposal-selection accuracy, cost, latency,
or software quality. Any effectiveness study must be separately designed and
scored.
