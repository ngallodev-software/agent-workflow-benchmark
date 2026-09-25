# Isolated Agent Execution Architecture

## Core abstraction

The reusable component is not a Docker script and it is not Codex-specific.

It is an **isolated agent envelope**:

```text
Task contract
  + prompt
  + explicitly allowed files
  + input hashes
  + runtime identity
  + credential policy
  + guardrails
  + output schema
  + reveal/coordination policy
        |
        v
Isolated agent runtime
        |
        v
Structured result + provenance
```

The A/B/C adjudication module is the first concrete coordination pattern built on this envelope.

## Layers

### 1. Task semantics

Defines what is being decided or produced.

Examples:

- routing labels;
- code implementation;
- security review;
- benchmark grading.

Task semantics must remain independent from the runtime implementation.

### 2. Runtime isolation

Defines what the agent can see and do.

Examples:

- OCI container;
- read-only root;
- workspace/input mounts;
- network policy;
- credential scope;
- process/resource limits.

### 3. Agent adapter

Defines how the runtime invokes the agent.

Current implementation:

- Codex CLI.

Future adapters may include:

- Claude Code;
- Gemini CLI;
- Inspect SWE agents;
- custom model loops;
- human/manual adapters.

### 4. Output contract

Defines a machine-readable result.

Examples:

- adjudication labels;
- patch/artifact manifest;
- grader scores;
- acceptance decision.

JSON Schema remains the preferred boundary.

### 5. Coordinator

The coordinator controls information flow across independent runs.

For A/B/C:

- start A/B independently;
- wait for both;
- validate both;
- reveal only after both complete;
- derive disagreements;
- send only disputes to C;
- freeze final result.

For benchmark arms:

- start matched arms;
- keep hidden evaluator unavailable;
- seal execution;
- introduce scorer only after seal;
- publish paired results after both arms are complete.

## Reuse profiles

### Blinded adjudication

- no repository mount;
- provider network only;
- task files read-only;
- narrow structured result.

### Coding benchmark arm

- private writable repository/worktree;
- build/test environment;
- provider network;
- no sibling-arm mount;
- no hidden scorer before execution seal.

### Post-seal scorer

- sealed candidate worktree read-only;
- scoring bundle read-only;
- scorer output writable;
- only scorer-specific credentials.

These profiles share the same envelope but use different policies.

## What should become generic

Good candidates:

- runtime/image definition;
- file mount declarations;
- prompt/template declaration;
- agent adapter;
- credentials allow/deny policy;
- environment/network policy;
- resource limits;
- output schema;
- result paths;
- artifact hashes;
- parallel group;
- reveal policy;
- runtime manifest.

## What should remain task-specific

- routing taxonomy;
- oracle labels;
- benchmark score formulas;
- A/B/C majority semantics;
- hidden evaluator logic;
- final publication criteria.

Those belong in versioned task/coordinator modules.

## Generic module direction

The current `abc-adjudication-module/v1` should be treated as the first specialization.

After at least one second use case, extract the common subset into:

`agent-workflow-benchmark/isolated-agent-module/v1`

Then make A/B/C adjudication a coordination plugin over that generic envelope.

Avoid premature generalization before a second concrete use case proves the abstraction.
