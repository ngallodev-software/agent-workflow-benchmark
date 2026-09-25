# Comparative Decision Study

Benchmark 0.4.0 adds a study lane for the three live Agent-Workflow routing semantic decisions. It is separate from BM3–BM6 because those studies measure workflow/lifecycle treatments, while this lane measures bounded decision evidence.

## Evidence flow

~~~mermaid
flowchart LR
    S[Frozen study specification] --> C[Public-safe inference corpus]
    C --> R[decision-study-run]
    R --> D[Deterministic control]
    R --> J[One batched TypeSafe/Jev call per case]
    J --> O1[Choice observation]
    J --> O2[Noul observation]
    J --> O3[Score observation]
    J --> Q[One provider-request record]
    A[Separately frozen blinded oracle] --> P[decision-study-report]
    O1 --> P
    O2 --> P
    O3 --> P
    Q --> P
    P --> M[Correctness / calibration / reliability / efficiency]
    M --> U[decision-study-publish-prepare]
~~~

The run command has no oracle argument. run-manifest.json records oracle_seen_during_inference: false. Oracle labels are first loaded by the reporting stage.

## Commands

~~~bash
agent-workflow benchmark decision-study-corpus-export ./routing-corpus.json
agent-workflow benchmark decision-study-oracle-view-export ./oracle-authoring-view.json

# A and B independently label the exact same authoring-view artifact.
agent-workflow benchmark decision-study-adjudication-validate \
  ./oracle-authoring-view.json ./adjudication-a.json
agent-workflow benchmark decision-study-adjudication-validate \
  ./oracle-authoring-view.json ./adjudication-b.json

# Export only A/B-disputed cases/seams for independent C adjudication.
agent-workflow benchmark decision-study-oracle-disputes \
  ./oracle-authoring-view.json ./adjudication-a.json ./adjudication-b.json \
  ./oracle-disputes-for-c.json

# If disputes exist, C labels the dispute view without seeing A/B labels.
agent-workflow benchmark decision-study-adjudication-validate \
  ./oracle-disputes-for-c.json ./adjudication-c.json

# Freeze after majority resolution; optional --resolutions records genuine
# three-way discussion outcomes or oracle_conflict_unresolved seams.
agent-workflow benchmark decision-study-oracle-freeze \
  ./oracle-authoring-view.json ./adjudication-a.json ./adjudication-b.json \
  ./oracle.json \
  --oracle-version routing-semantic-oracle-v1.0.0 \
  --c-view ./oracle-disputes-for-c.json \
  --c-pass ./adjudication-c.json

agent-workflow benchmark decision-study-validate ./routing-corpus.json --oracle ./oracle.json

# Inference still receives no oracle.
agent-workflow benchmark decision-study-run ./routing-corpus.json ./run
agent-workflow benchmark decision-study-report ./run ./oracle.json
agent-workflow benchmark decision-study-publish-prepare ./run ./oracle.json ./public
~~~

The active Agent-Workflow configuration must use comparative decision mode and have a ready TypeSafe runtime. The production decision boundary is reused; the benchmark does not implement a second semantic-routing algorithm.

## Pre-adjudication runtime gate

Before the first real A/B oracle pass for `routing-semantic-v1`, the adjudicator execution runtime must complete **P0A Inspect integration and parity qualification**.

This is an infrastructure gate only. It does not change the frozen corpus, authoring view, oracle protocol, metrics, or inference semantics.

The direct-Docker runner remains the rollback/reference backend. The preferred path is Inspect AI + Inspect SWE + Docker sandbox after qualification. Real A/B labels must not be produced during the P0A synthetic parity work.

See [Inspect AI Integration Plan for Independent Oracle Adjudication](plans/2026-09-25-inspect-adjudication-integration-plan.md).

Implementation is available in benchmark 0.4.1. Follow [Inspect Oracle Adjudication — Debian Operator Guide](INSPECT_ORACLE_ADJUDICATION.md). The real A/B and C commands require a passing qualification manifest bound to the same module and runtime-lock hashes.

## Independent oracle adjudication contracts

The benchmark now operationalizes the already-frozen A/B/C oracle protocol without changing study semantics.

Each completed adjudication pass uses schema `agent-workflow-benchmark/decision-study-adjudication-pass/v1` and records:

- the study and dataset identity;
- the frozen oracle protocol version;
- the SHA-256 of the exact blinded view the adjudicator received;
- a distinct adjudicator identifier;
- an attestation that the pass was independent, treatment outputs were not seen, and other adjudicator labels were not seen;
- one label object per case containing exactly the seams present in that adjudicator's view.

A and B must validate against the exact same `oracle-authoring-view.json`. The dispute command compares their completed passes only after both exist, then emits `decision-study-oracle-dispute-view/v1`. That C view includes only disputed cases and disputed seam identities. It excludes A/B labels, corpus construction tags, deterministic outputs, semantic outputs, and comparison results.

The freeze command enforces the frozen protocol mechanically:

1. A/B exact agreement becomes the oracle label.
2. A/B disagreement requires a distinct C adjudicator and the exact blinded C dispute view.
3. Two-of-three agreement becomes the oracle label.
4. A genuine three-way categorical conflict or 0/1/2 risk split requires a recorded discussion artifact using `decision-study-adjudication-resolutions/v1`.
5. A discussion may resolve to a valid frozen label or remain explicitly `oracle_conflict_unresolved`.
6. The final comparative-eval oracle bundle is marked frozen and the command persists the SHA-256 of the exact file written.

The freeze command writes two artifacts:

- `oracle.json` — the frozen comparative-eval oracle bundle;
- `oracle.json.manifest.json` — a freeze manifest containing the oracle SHA-256, exact authoring-view SHA-256, A/B/C adjudicator IDs, pass hashes and completion timestamps, the C dispute-view hash when used, the discussion-resolution artifact hash when used, and final adjudication counts.

Retain both files before any live comparative inference begins. The manifest makes the oracle freeze identity reconstructable without relying on terminal output.

An explicitly unresolved conflict is valid study evidence. It is excluded with reason `oracle_conflict_unresolved`; it is not silently rewritten as `oracle_missing` and no label is invented to preserve sample size.

The tooling can validate artifact identity and recorded attestations, but it cannot itself prove that two people or agents were genuinely independent. Independence remains a procedural requirement of the study.


## Frozen study contract

The current preregistered study is routing-semantic-v1. It freezes:

- the three routing seams and semantic types;
- the task-class taxonomy and semantic-risk rubric;
- minimum 100 oracle-eligible cases per seam, target 120 shared cases;
- 95% interval policy and deterministic 10,000-resample paired bootstrap;
- p90 only at n >= 20 and p95 only at n >= 40;
- ECE publication only at n >= 100;
- explicit exclusion reason codes;
- independent blinded oracle requirements;
- batch/request accounting that counts one provider call once.

## Public artifact

decision-study-publish-prepare creates a public-safe evidence tree with the corpus, frozen oracle, machine-readable study report, Markdown report, neutral observations, provider-request summaries, exclusions, outcomes, hashes, and a publication manifest.

Raw TypeSafe HTTP request/response audit logs are not copied.

A development run below the sample threshold is rendered as study_eligible: false; it remains useful for instrumentation validation but is not a generalized effectiveness result.

## Portfolio-safe implementation status

Safe to render now:

- The study protocol is preregistered before the full oracle/results exist.
- The inference runner structurally cannot receive an oracle path.
- One Jev request is decomposed into three decision observations while request-level latency/tokens remain single-counted.
- The benchmark and normal Agent-Workflow runtime reuse the same receipt-to-evidence conversion.
- Publication eligibility is machine-readable and does not depend on whether Jev wins.

Do not render claims that Jev improves routing correctness, quality, latency, or cost until the full independently labeled study is complete.


## Frozen corpus and oracle handoff

The packaged inference corpus is `routing-semantic-corpus-v1.0.0` with **120 public-safe cases**. Every case is oracle-eligible for the three live routing seams.

The corpus intentionally includes several construction strata:

- straightforward single-intent requests;
- missing routing metadata;
- stale or misleading declared task type;
- missing user authorization/choice;
- stale interaction flags where no new decision is actually required;
- high-consequence production/security contexts;
- mixed-intent requests;
- terse/ambiguous requests.

Construction tags are retained in the frozen corpus for later stratified analysis but **are removed from the oracle-authoring view**. The adjudicator view contains only:

- case ID;
- request text;
- observed declared metadata;
- the frozen task-class taxonomy and semantic-risk rubric;
- oracle eligibility.

It contains no deterministic outputs, Jev outputs, probability evidence, comparison results, or construction tags.

The adjudicator must produce the frozen oracle without access to treatment results. The inference corpus and final oracle are separate versioned artifacts.
