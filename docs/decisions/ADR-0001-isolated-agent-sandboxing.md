# ADR-0001 — OCI Containers for Independent Agent Isolation

- **Status:** Accepted
- **Date:** 2026-09-25
- **Initial use:** `routing-semantic-v1` oracle adjudication

## Context

Independent A/B adjudicators must receive the same blinded task artifact while remaining unable to observe each other's labels or treatment results.

Separate physical machines would satisfy this but are operationally unnecessary for the non-adversarial study threat model.

Git worktrees do not provide a sufficient information boundary because they share Git history/refs and normally expose broader host filesystem and credential context.

## Decision

Use separate OCI-compatible containers as the isolation boundary.

The required contract is:

- explicit input allowlist;
- read-only task inputs;
- private output path;
- read-only root filesystem;
- dropped Linux capabilities;
- no-new-privileges;
- no Docker socket;
- ephemeral agent configuration/home;
- credential allowlisting/denial;
- no cross-agent mount;
- delayed result reveal;
- hash-bound inputs and outputs.

Docker Engine is the current implementation on Debian.

## Consequences

This gives stronger and more reproducible separation than worktrees while keeping A/B/C on one host.

Docker daemon/root are outside the isolation threat model.

A future runtime may replace Docker if it preserves or strengthens the same contract.

## Rejected alternatives

### Separate machines

Not required for the current independence definition. Higher operational cost without adding study-relevant evidence.

### Worktrees alone

Useful for coding benchmark arms, but not a sufficient isolation boundary for blinded adjudicators.

### Raw processes

Insufficient filesystem, process, and credential separation.

## Future abstraction

The A/B/C workflow is represented as a versioned module rather than being generalized by adding unrelated modes to the frozen routing script.

New infrastructure should adopt OCI-compatible images and a declarative execution contract, and should evaluate Inspect AI or SWE-ReX before adding more custom sandbox orchestration.
