# Routing Semantic v2 — Benchmark Implementation Boundary

The v2 work repairs oracle/evidence mechanics while leaving the published
`routing-semantic-v1` cohort immutable.

## Pass v2

`agent-workflow-benchmark/decision-study-adjudication-pass/v2` requires every
eligible seam to contain:

- the label;
- 1–3 bounded decisive case-evidence statements;
- the rubric rule;
- an ambiguity state.

These are explicit decision justifications. They are not hidden chain-of-thought.

The v2 wrapper, schema validator, dispute path, and human-resolution renderer all
preserve this evidence. The C dispute view still excludes A/B labels and
justifications.

## Provenance correction

New adjudication provenance separates:

- `final_output_usage`;
- `aggregate_session_usage`;
- `provider_request_count`;
- `model_call_count`;
- optional reasoning-summary observation metadata.

Provider reasoning summaries remain private supplementary evidence. Their absence
does not invalidate the authoritative structured justification.

## Evidence preflight

Before freezing a real v2 cohort:

~~~bash
export V2_ADJUDICATION_MODEL='openai-api/codex-lb/<model-id>'
bash scripts/adjudication/v2-evidence-preflight.sh
~~~

This live synthetic preflight exercises:

- **IA-9** — rationale round-trip through A/B/C, dispute blinding, and the real
  human-review renderer;
- **IA-10** — final-output versus aggregate-session usage scope;
- **IA-11** — optional reasoning-summary observation path.

The artifact deliberately reports:

~~~text
real_cohort_ready: false
~~~

Passing IA-9/10/11 does **not** authorize real v2 adjudication. The real v2
dataset identity, blinded view, module, runtime lock, and full IA-1..IA-11
qualification must still be frozen.

## Next freeze boundary

Only after the preflight passes should the exact v1 case content be cloned under a
new v2 dataset identity and its canonical blinded authoring view/module hashes be
frozen.

That cohort is a methodological replication. Candidate/control inference is not
automatically rerun unless the new oracle changes enough labels to justify a
preregistered re-score or replication.
