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

agent-workflow benchmark decision-study-validate ./routing-corpus.json
agent-workflow benchmark decision-study-run ./routing-corpus.json ./run

# The frozen oracle is created independently from oracle-authoring-view.json.
agent-workflow benchmark decision-study-validate ./routing-corpus.json --oracle ./oracle.json
agent-workflow benchmark decision-study-report ./run ./oracle.json
agent-workflow benchmark decision-study-publish-prepare ./run ./oracle.json ./public
~~~

The active Agent-Workflow configuration must use comparative decision mode and have a ready TypeSafe runtime. The production decision boundary is reused; the benchmark does not implement a second semantic-routing algorithm.

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
