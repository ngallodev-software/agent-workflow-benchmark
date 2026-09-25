# A/B/C Adjudication Module

This module turns the independent adjudication pattern into a declarative, reusable unit.

The module contract is:

`agent-workflow-benchmark/abc-adjudication-module/v1`

A module instance describes:

- the study/task identity;
- the exact prompt template;
- required files and frozen hashes;
- adjudicator roles and IDs;
- container/runtime setup;
- provider credential policy;
- filesystem/network/tool guardrails;
- structured output contract;
- A/B reveal policy;
- C disagreement routing;
- final result/freeze locations.

The first concrete instance is:

`routing-semantic-v1.module.json`

## Why a module?

The current routing-semantic-v1 harness proved that the A/B/C pattern is broader than one study.

The reusable workflow is:

```text
module spec
   |
materialize A + B
   |
run independently
   |
validate both
   |
reveal/compare after both complete
   |
route only disagreements to C
   |
majority or recorded resolution
   |
freeze result + manifest
```

This can support other tasks where an independent oracle, grader, or reviewer ensemble is useful.

Examples:

- benchmark rubric adjudication;
- human/model grading calibration;
- security-review consensus;
- labeling ambiguous datasets;
- acceptance/readiness decisions;
- post-run qualitative scoring;
- benchmark result verification.

## Module fields

### `task`

Identifies the study/dataset/protocol. This keeps an adjudication output bound to the exact semantic contract it belongs to.

### `runtime`

Defines:

- runtime kind;
- Dockerfile/image;
- agent CLI package/version;
- agent entrypoint;
- configuration mount;
- network requirement.

The current module uses an OCI/Docker image containing Codex CLI.

### `prompt`

Points to the prompt template and lists variables that are substituted per adjudicator.

Prompts are files, not inline strings, so they can be versioned, reviewed, hashed, and diffed.

### `required_files`

Defines every file a role may receive:

- logical ID;
- source repository/path;
- target path;
- expected SHA-256 when frozen;
- authorized roles;
- read-only requirement.

This field is the main information-flow allowlist.

A file absent from this list should not be mounted into an adjudicator container.

### `roles`

Defines exactly two primary independent adjudicators and one conditional tiebreaker.

The contract intentionally distinguishes role from runtime/model identity. A future module can therefore use:

- Codex A + Claude B + human C;
- three different model versions;
- two humans + one model;
- three identical agents in isolated sessions.

### `credentials`

Defines credential transport and deny rules.

The current routing module accepts an external provider env file but explicitly denies `TYPESAFE_*` variables.

Secret values are never part of the module or run manifest.

### `guardrails`

Records the required isolation contract:

- no repository mount;
- no Docker socket;
- read-only container root;
- all Linux capabilities dropped;
- no-new-privileges;
- read-only agent sandbox;
- no web search;
- no cross-agent visibility;
- no treatment outputs;
- no prior labels;
- no overwrite of completed results.

These are declarative requirements, not comments.

### `output`

Defines:

- how the model-facing JSON Schema is generated;
- the final adjudication-pass schema;
- result filename;
- hash-sidecar requirement.

### `coordination`

Defines protocol-level orchestration:

- A/B start in parallel;
- neither result is revealed until both complete;
- comparison command;
- C input artifact;
- majority/discussion policy;
- unresolved marker;
- freeze command;
- inference gate.

### `results`

Defines the runtime root and final authoritative artifacts.

This lets a future coordinator locate results without embedding study-specific paths in code.

## Module validation

The module JSON is validated as part of the benchmark package schema set.

Future generic tooling should also perform semantic validation such as:

- unique adjudicator IDs;
- unique result subdirectories;
- A and B must both receive the same frozen primary input;
- C must not receive A/B label artifacts;
- required paths exist;
- frozen SHA-256 values match;
- denied credential prefixes do not appear in the container environment;
- declared guardrails are realizable by the selected runtime.

## Relationship to the current Docker runner

The existing routing Docker runner remains the historical/reference executor for `routing-semantic-v1`.

The module file captures its configuration declaratively.

Do not silently replace the frozen study semantics. The execution decision was amended before any real oracle labels existed:

1. retain the merged direct-Docker runner as the reference/rollback backend;
2. implement an Inspect AI backend against the same module semantics;
3. qualify it only on synthetic fixtures before real adjudication;
4. compare generated inputs, runtime identity, output contracts, guardrails, failure semantics, and result manifests against the reference backend;
5. use Inspect for the real A/B/C oracle only after the pre-adjudication qualification gates pass;
6. if qualification fails, restart fresh A/B sessions using the reference backend.

The integrated plan is `docs/plans/2026-09-25-inspect-adjudication-integration-plan.md`.

## Future generic runner

A generic runner can expose commands such as:

```bash
agent-workflow benchmark module validate MODULE.json
agent-workflow benchmark module prepare MODULE.json --root RUN_ROOT
agent-workflow benchmark module run-primary MODULE.json --root RUN_ROOT
agent-workflow benchmark module compare MODULE.json --root RUN_ROOT
agent-workflow benchmark module run-tiebreaker MODULE.json --root RUN_ROOT
agent-workflow benchmark module freeze MODULE.json --root RUN_ROOT
```

The runner should not know what "routing semantics" means. It should only understand:

- roles;
- files;
- hashes;
- prompts;
- runtime;
- output contracts;
- guardrails;
- coordination policy.

Study-specific comparison/freeze behavior should be supplied through versioned coordinator adapters.

## Extension beyond adjudication

The same module shape suggests a more general **isolated-agent module** abstraction.

A/B/C adjudication would then be one coordination policy over the same execution envelope used by:

- paired benchmark arms;
- blind implementation agents;
- independent scorers;
- red-team/reviewer panels;
- repair/verification agents.

That extraction should happen only after at least one additional use case proves which fields are truly generic.
