# Agentic-Jev SWE-Lancer manager v2 — preregistered effectiveness study

**Study ID:** `agentic-jev-swe-manager-v2`  
**Study version:** `2.0.0-preregistered`  
**Status:** preregistered implementation; no v2 effectiveness outcomes observed  
**Primary question:** does the qualified deterministic Jev manager checkpoint improve official SWE-Lancer manager correctness relative to the same coding agent without the live checkpoint?

## Treatment

Both paired arms use GPT-6 Luna/high, the same benchmark decision-support skill v6,
the same pinned Inspect Evals task/scorer, and the same visible decision-record
contract.

~~~text
control
  GPT-6 Luna/high
  + decision-support skill v6
  + no live manager checkpoint

treatment
  identical model/skill
  + host-side jev_manager_decision
  + deterministic request builder v2
  + SWE-manager completeness policy v2
~~~

The treatment host injects the exact authoritative task title, description, and full
proposal text from the frozen SWE-Lancer source. The coding agent supplies sourced
repository evidence and explicit verification scope.

The treatment is advisory. Official repository/task evidence and the official scorer
remain authoritative.

## Qualified treatment identity

The live pre-study qualification reused already-observed `18796-manager-0` and
therefore consumed no fresh effectiveness case.

Frozen qualification identity:

- benchmark qualification commit: `4338b6498eed520380dbd215344d7b37d183863e`;
- policy: `swe-manager-choice-v2@2.0.0`;
- request builder: `2.0.0`;
- live request SHA-256:
  `100091b2f9204c1351c469bfc2d1cd7a0f73834a645e17363a331cc015df85f6`;
- resolved Jev model: `jev-1.13.0`;
- all completeness checks passed;
- no redaction or silent truncation occurred.

The committed qualification-lock artifact is part of the pre-run evidence.

## Fresh cohort

Target: **30 paired official SWE-Lancer `swe_manager` tasks** from the pinned
Inspect Evals commit
`190dfa27bc2e9b3e966ea6e8a682626d55b513c0`.

Selection reads only:

- `question_id`;
- `variant`;
- `set`;
- `title`.

No correct-proposal/gold field may be read for selection, prompting, stopping, or
exclusion.

The exclusion registry contains **36 unique previously observed official manager
tasks**:

- six tasks from the earlier external-scout/manager trace work;
- all 30 tasks from `agentic-jev-swe-manager-v1`.

The qualification task is already included in the v1 set.

Selection method:

~~~text
sort ascending by sha256("agentic-jev-swe-manager-v2:" + sample_id)
take first 30 after exclusions
~~~

Arm order is deterministically counterbalanced per selected sample from its frozen
selection digest. Exact 15/15 first-arm balance is not required.

## Primary estimand and scoring

The sole correctness authority is the official pinned Inspect Evals SWE-Lancer
scorer.

Primary estimand:

~~~text
treatment attempt accuracy - control attempt accuracy
~~~

over all 30 frozen pairs.

A missing/non-binary official arm score counts incorrect at attempt level. Treatment
no-call cases remain in the treatment denominator.

Report together:

- control and treatment attempt accuracy;
- treatment-minus-control point estimate;
- deterministic paired bootstrap interval;
- four paired correctness cells;
- exact McNemar result;
- score availability/reliability;
- Jev call and context-completeness counts;
- request-history/revision process evidence;
- visible decision-record coverage;
- coding-agent latency/token overhead;
- Jev-service token/duration overhead;
- limitations.

Called-only and successful-call-only subsets are descriptive/self-selected only.

Semantic agreement with Jev is never correctness.

## Request/rebuild policy

When `jev_manager_decision` is available, the study skill directs the treatment
agent to use one checkpoint after repository inspection and before final proposal
submission.

The host batch contains:

1. proposal Choice with `insufficient_evidence`;
2. evidence-sufficiency Noul.

A changed second request is allowed only after the checkpoint permits rebuilding and
the agent gathers materially new evidence. The skill documents at most one changed
revision. An unchanged state+questions request is rejected by the builder.

Low Choice confidence alone is not a rebuild trigger.

Treatment no-call or tool failure remains study evidence and does not trigger
outcome-dependent retry/exclusion.

## Observable decision evidence

Both arms must emit the same bounded final JSON decision record. `evidence_refs`
may be strings or structured `{"source": ..., "fact": ...}` objects; the benchmark
normalizes them deterministically so useful visible evidence is not discarded solely
because the model chose a structured representation.

Hidden chain-of-thought is neither requested nor exported.

## Outcome-read barrier

For each pair, both arms execute before the benchmark reads official score evidence.
Do not stop, refreeze, exclude, or retry a sample because interim correctness looks
good or bad.

A technical failure is preserved. Repair requires a new run root; do not overwrite
partial evidence.

## Publication/privacy

Raw Jev requests/responses, provider traffic, Inspect logs, credentials, hidden
reasoning, and local paths remain private.

The sanitized public bundle contains paired public-safe trial evidence, aggregate
metrics, runtime/cohort identities, and hashes of retained private artifacts,
including v2 request-history ledgers.

Dollar cost remains unavailable unless an authoritative billing schedule is frozen
before execution; provider tokens and duration are reported separately.

## Operator sequence

~~~bash
bash scripts/agentic-jev/p9-freeze-swe-manager-v2-study.sh
bash scripts/agentic-jev/p9-prepare-swe-manager-v2-study.sh
bash scripts/agentic-jev/p9-run-swe-manager-v2-paired.sh
bash scripts/agentic-jev/p9-prepare-swe-manager-v2-publication.sh
~~~

Do not run the paired study until the preregistered implementation is merged and the
frozen cohort has been inspected only for identity/freshness—not outcomes.
