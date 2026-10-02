# Agentic Jev SWE-Lancer Manager v1 handoff

**Date:** 2026-10-02  
**Status:** implementation merged; preregistered; host execution intentionally left to the operator  
**Study ID:** `agentic-jev-swe-manager-v1`

## Canonical merged state

Use current repository heads, but the implementation completed in this work is anchored by:

- `agent-workflow-comparative-eval@7d23ac11eb5c0e71dc5a75e2375e09d3333fec53`
- `agent-workflow@b348d851218b09ceeb18a653c5106670989fd6d4`
- `agent-workflow-benchmark@d3fb85ef1ab72a417d6c464e20f7f3f0c3f92674`
- Jev skill source identity: `ngallodev-software/jev-decision-support@d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`
- pinned Inspect Evals source: `UKGovernmentBEIS/inspect_evals@190dfa27bc2e9b3e966ea6e8a682626d55b513c0`

Before doing any further work, verify current heads and inspect any commits made after these anchors. Do not reset or discard newer work.

## What changed

The deeper Luna study was standardized around upstream Inspect Evals rather than growing another custom evaluation framework.

`agent-workflow-comparative-eval` 0.3.2 now owns the provider-neutral comparison semantics:

- preregistered `agentic-jev-swe-manager-v1` study;
- paired decision trial and report schemas;
- official SWE-Lancer correctness imported rather than redefined;
- treatment-minus-control attempt accuracy;
- four paired correctness cells;
- deterministic paired bootstrap interval;
- two-sided exact McNemar test;
- Jev exposure/context process evidence;
- visible justification/reconciliation coverage;
- explicit intent-to-treat and claim boundaries.

`agent-workflow-benchmark` 0.6.5 now owns execution/evidence collection:

- imports upstream `inspect_evals.swe_lancer.swe_lancer`;
- uses the official upstream `swe_lancer_scorer()`;
- adds only a no-metric auxiliary scorer to capture the proposal actually written to `manager_decisions.json`;
- freezes 30 fresh manager task IDs using a deterministic hash of official sample ID;
- excludes every previously observed Agentic-Jev manager task before selection;
- reads no gold/correct-proposal fields during cohort selection;
- pairs the same GPT-6 Luna/high model and the same current Jev skill in both arms;
- control has no live Jev bridge;
- treatment has the host-side Jev bridge;
- prompts both arms only to use installed skills when applicable, without naming or requiring Jev;
- requires a bounded visible decision record: selected proposal, justification, evidence refs, tradeoff, semantic-evidence reconciliation, remaining uncertainty;
- never requests or exports hidden chain-of-thought;
- inspects private Jev request context after execution for requirement/proposal coverage and agent-judgment leakage;
- preserves Inspect `.eval` logs as canonical execution evidence.

`agent-workflow` was changed only to accept additive comparative-eval 0.3.2 while preserving 0.3.1 compatibility.

## Validation completed

Comparative-eval PR #38 passed Python 3.11 and 3.13 CI and was squash-merged.

Agent-Workflow PR #55 passed the full matrix:

- Ubuntu Python 3.11
- Ubuntu Python 3.12
- Ubuntu Python 3.13
- macOS Python 3.12
- Windows release validation

Benchmark PR #90 passed all three jobs:

- full unit/build suite;
- Inspect compatibility/guardrail job;
- Agentic-Jev integration job, including installation and construction of the pinned upstream SWE-Lancer task and validation of its comparability version `1`, full task version `1-B`, and interface version `B`.

## Important study boundaries

This is the first intended effectiveness study, not another activation smoke test.

Primary estimand:

```text
official SWE-Lancer treatment attempt accuracy
-
official SWE-Lancer control attempt accuracy
```

The treatment is **availability of live Jev evidence**, not “Jev was actually called.” Treatment no-call tasks remain in the denominator. Any called-only or successful-call-only subset is self-selected and descriptive only.

Semantic agreement with Jev is never correctness.

Missing/non-binary arm scores are counted as incorrect at attempt level under the preregistered primary analysis rather than silently excluded.

With 30 pairs, report point estimate, interval, discordant counts, McNemar result, reliability/process evidence, and limitations together. Do not overclaim sensitivity to small effects or cross-benchmark generalization.

## Host execution

Host-side execution is intentionally left to the operator. Do not attempt remote host runs unless explicitly asked in a future thread.

Canonical operator sequence from a current clean benchmark checkout:

```bash
bash scripts/agentic-jev/p7-freeze-swe-manager-study.sh
bash scripts/agentic-jev/p7-prepare-swe-manager-study.sh
bash scripts/agentic-jev/p7-run-swe-manager-paired.sh
```

Requirements:

- host-only `TYPESAFE_API_KEY`;
- reachable Codex-LB;
- Docker;
- Codex CLI;
- prior immutable Agentic-Jev external scout cohort manifest;
- fresh/non-empty study roots must never be overwritten.

A failed or partial execution remains evidence. After any material repair use a fresh `AGENTIC_JEV_SWE_MANAGER_RUN_ROOT`; do not delete the failed run.

Do not inspect new cohort gold answers before freeze or use them to alter prompts, selection, stopping, or exclusions.

## After the operator run

The next agent should:

1. verify the run used the frozen cohort and pinned source identities;
2. inspect `run-manifest.json`, `paired-report.json`, per-sample `paired-trial.json`, Inspect logs, and private Jev receipt summaries;
3. check Jev activation, context-completeness diagnostics, visible justification/reconciliation coverage, API-key absence, and execution failures before interpreting correctness;
4. report the preregistered intent-to-treat paired outcome first;
5. report called-only analyses only as descriptive;
6. preserve raw provider/Jev context privately and publish only sanitized evidence;
7. if evidence is publishable, update the benchmark/results/portfolio-facing handoffs without rewriting earlier exploratory history.

## Related documents

- `docs/AGENTIC_JEV_SWE_MANAGER_V1.md`
- `docs/AGENTIC_JEV_CURRENT_MODEL_QUALIFICATION.md`
- `scripts/agentic-jev/README.md`
- comparative-eval study resource: `agentic-jev-swe-manager-v1.study.json`

The earlier six-task manager pilot remains exploratory mechanism evidence and must not be folded into this fresh effectiveness cohort.
