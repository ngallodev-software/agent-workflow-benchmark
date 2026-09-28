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

## Frozen adjudicator identity

The methodological replication keeps the v1 adjudicator model path fixed:

- model: `openai-api/codex-lb/deepseek-flash`;
- request mode: Responses API via `{"responses_api": true}`.

The v2 evidence-contract changes are the methodological change being tested. GPT-6 Luna is reserved for the separate `agentic-jev-pilot-v1` coding-agent study and must not be substituted into the v2 oracle replication.

## Evidence preflight

Before freezing a real v2 cohort:

~~~bash
export V2_ADJUDICATION_MODEL='openai-api/codex-lb/deepseek-flash'
export V2_ADJUDICATION_MODEL_ARGS_JSON='{"responses_api":true}'
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

The exact v1 case content has already been registered under the draft v2 dataset
identity. Only after the preflight passes should its canonical blinded authoring
view, adjudication module, and runtime hashes be frozen.

That cohort is a methodological replication. Candidate/control inference is not
automatically rerun unless the new oracle changes enough labels to justify a
preregistered re-score or replication.
