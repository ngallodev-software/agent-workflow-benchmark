# Agentic Jev SWE-Lancer manager effectiveness study v1

**Status:** preregistered implementation; do not inspect outcome/gold fields during cohort selection  
**Study ID:** `agentic-jev-swe-manager-v1`  
**Model:** GPT-6 Luna via `openai-api/codex-lb/gpt-6-luna`, reasoning effort `high`  
**Semantic skill:** `ngallodev-software/jev-decision-support@d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`

## Purpose

This is the first Agentic-Jev lane intended to estimate a task-outcome treatment effect rather than merely tool activation. It uses the official Inspect Evals SWE-Lancer `swe_manager` task and scorer as the benchmark substrate.

The treatment question is deliberately narrow:

> On a fresh fixed cohort of SWE-Lancer manager tasks, does making live Jev semantic evidence available to GPT-6 Luna change official proposal-selection accuracy relative to the same Luna model with the exact same current Jev decision skill installed but no live Jev tool?

The control therefore retains the skill. Only the live host-side Jev bridge differs.

## Standard components retained upstream

The runner imports the pinned upstream `inspect_evals.swe_lancer.swe_lancer` task. Inspect/Inspect Evals remain responsible for:

- the SWE-Lancer dataset and sample construction;
- the official manager task prompt and sandbox;
- official scoring against the correct proposal;
- the standard Inspect `.eval` execution log;
- sample filtering, solver execution, and evaluator lifecycle.

The benchmark does **not** recreate the SWE-Lancer gold answer or correctness scorer.

One auxiliary scorer with no aggregate metric reads the already-required `/app/expensify/manager_decisions.json` and records the proposal ID actually written by the agent. This exists only to bind decision-change analysis to the applied manager decision rather than to prose in the final response. The official SWE-Lancer scorer remains the sole correctness authority.

## Frozen source

The cohort freezer pins:

- Inspect Evals repository: `UKGovernmentBEIS/inspect_evals`;
- commit: `190dfa27bc2e9b3e966ea6e8a682626d55b513c0`;
- SWE-Lancer eval version: `1-B`;
- the exact task CSV SHA-256;
- the exact official scorer source SHA-256.

The source is copied into the private study directory and validated again before execution.

## Fresh cohort

The target cohort is 30 `swe_manager` tasks from the diamond split.

Selection is deterministic:

```text
ascending sha256("agentic-jev-swe-manager-v1:" + official_sample_id)
```

The selector reads only:

- `question_id`
- `variant`
- `set`
- `title`

It does not parse `manager_data`, `correct_proposal_id`, or other gold-adjacent fields.

Every SWE-Lancer manager task previously observed in the Agentic-Jev external scout is loaded from the immutable prior cohort manifest and excluded **before** selection. The freeze fails closed when that prior manifest is absent.

The same selection digest also freezes which arm runs first for each pair, providing deterministic outcome-blind arm-order assignment. The hash-parity rule does not guarantee an exact 15/15 first-arm split; the paired primary analysis does not depend on exact order balance, and the frozen order distribution should be reported descriptively.

## Arms

### Control

GPT-6 Luna/high with the current source-synchronized Jev decision-support skill installed. No live Jev bridge is exposed.

### Treatment

The exact same model, reasoning effort, system contract, and skill, plus the host-side `jev_system_one` bridged tool. `TYPESAFE_API_KEY` stays on the host and is never injected into the SWE-Lancer sandbox.

Both arms must still complete the official task by writing `manager_decisions.json`. Both also return a bounded visible JSON decision record containing:

- selected proposal ID;
- observable evidence-based justification;
- evidence references;
- decisive trade-off;
- semantic-evidence reconciliation;
- remaining uncertainty.

This is the auditable reasoning evidence required by the comparative-evaluation lessons learned. Hidden chain-of-thought is neither requested nor exported.

## Context adequacy

For each successful treatment Jev receipt, the private host-side request is inspected after execution. The process metric checks:

- at least 50% token overlap with the visible task title;
- at least 25% token overlap with the visible issue description;
- at least 40% token overlap with the visible proposals;
- at least one Choice question;
- non-empty tool purpose;
- absence of agent-verdict keys such as `selected_proposal_id`, `preferred_option`, or `verdict` from the neutral Jev state.

These thresholds are a **process diagnostic**, not an exclusion gate and not a correctness metric. A treatment task with no Jev call remains in the primary treatment denominator.

Raw Jev request context stays private. The comparison record retains request hashes, aggregate and exact-call completeness counts, and resolved Jev model identities from successful receipts.

## Pre-run evidence hardening

Before any cohort freeze or outcome observation, the implementation was hardened to make the preregistered evidence auditable under failure as well as success:

- the three Phase 7 operator scripts use real shell parameter expansion rather than the accidentally escaped literal `\${...}` form present in the initial preregistered implementation;
- every Phase 7 Jev receipt is labeled with `agentic-jev-swe-manager-v1` rather than inheriting the earlier pilot study ID;
- a validated `run-start.json` is written before the first paired task and binds the frozen cohort hash, Inspect source/scorer identity, coding-agent runtime, benchmark git commit, runner/bridge hashes, package versions, and requested Jev model;
- execution refuses tracked benchmark-code drift so the runtime cannot silently differ from its committed source identity;
- successful receipts retain the resolved Jev model identity even when the operator leaves the Jev model request unset and the service chooses its configured default;
- nested Inspect model-usage records remain structured so latency/token overhead can be aggregated by comparative-eval;
- paired reports bind one source/runtime identity, preserve the actual frozen cohort artifact SHA, summarize paired end-to-end duration and coding-agent token overhead, report Jev receipt token/duration totals separately, and retain exact successful-call context-completeness counts.

These are preregistration implementation/evidence corrections made before the study is run. They do **not** change cohort selection, arm definitions, prompts, official correctness scoring, the intent-to-treat denominator, the primary estimand, the missing-score rule, or the preregistered inferential methods.

## Metrics and evidence origin

| Metric | Question | Data origin | Capture | Oracle | n / denominator | Public-safe reporting |
| --- | --- | --- | --- | --- | --- | --- |
| Control/treatment attempt accuracy | Does live Jev availability change task correctness? | official SWE-Lancer scorer | Inspect sample score after both paired arms execute | official correct proposal | all 30 frozen pairs; missing/non-binary arm score counts incorrect | counts, rates, Wilson intervals |
| Treatment - control accuracy | What is the paired effect estimate? | paired official scores | comparative-eval `build_paired_decision_report` | same | all frozen pairs | point estimate + deterministic paired bootstrap interval |
| Discordant pairs | Where did treatment change correctness? | paired official scores | four-cell paired classification | same | all frozen pairs | both-correct/both-wrong/control-only/treatment-only |
| Exact McNemar p-value | Are discordant correctness changes asymmetric? | control-only vs treatment-only counts | comparative-eval exact binomial/McNemar test | same | discordant pairs | two-sided exact p-value, never alone |
| Decision-change rate | Did the applied proposal change? | auxiliary capture of `manager_decisions.json` | no-metric evidence scorer | none | pairs with both applied IDs captured | count/rate, separate from correctness |
| Jev activation/success | Was live Jev actually used? | private host receipt ledger | per-treatment sample | none | all 30 treatment trials | call/success counts |
| Jev context completeness | Was enough neutral primary context supplied? | private Jev request + visible official prompt | fixed overlap/check rules above | none | successful calls with inspectable request | trial and exact-call complete/known counts; hashes only |
| Visible justification/reconciliation | Did Luna leave auditable decision evidence? | final visible assistant JSON | parser | none | all arms | presence/error counts; sanitized excerpts may be curated separately |
| Latency/token overhead | What execution overhead accompanies the treatment? | Inspect sample usage/time + sanitized Jev receipt summary | per arm/request | none | paired trials with observed fields / observed Jev requests | paired end-to-end duration and coding-agent token means/deltas/intervals; Jev service tokens and receipt duration reported separately, never summed across unlike models |
| Dollar cost overhead | What monetary overhead accompanies treatment? | authoritative provider billing/price schedule would be required | **not captured/frozen in v1** | none | unavailable | report as not captured; do not convert tokens to dollars post hoc without a pre-frozen authoritative pricing source |

Semantic agreement with Jev is never treated as correctness.

## Outcome-read barrier

For each task, arm order is frozen before execution. Both arms execute before benchmark code reads official scorer outcomes into the paired comparison record. The runner does not branch on the first arm's score to decide whether the second arm runs.

Inspect necessarily computes each arm's score as part of its normal evaluation lifecycle, but the benchmark runner treats those scores as opaque until both arms for the pair have completed.

## Primary analysis

The primary estimand is intent-to-treat **availability of live Jev evidence**:

```text
treatment official attempt accuracy - control official attempt accuracy
```

Treatment no-call tasks remain treatment observations. A "Jev was actually called" subset is agent-selected and can therefore be reported only descriptively.

The report includes:

- both arm attempt accuracies and Wilson intervals;
- paired accuracy difference and deterministic paired-bootstrap interval;
- the four paired correctness cells;
- two-sided exact McNemar p-value;
- Jev exposure;
- decision-change rate;
- observable justification/reconciliation coverage;
- execution reliability.

With 30 pairs this is a bounded first effectiveness study, not a design for detecting small effects. Point estimate, interval, discordant counts, and limitations must be reported together. V1 does not freeze authoritative provider billing data, so token overhead must not be presented as dollar cost; monetary overhead is explicitly unavailable unless a separately frozen, outcome-blind pricing source is added before execution.

## Operator sequence

Freeze before looking at new outcomes:

```bash
bash scripts/agentic-jev/p7-freeze-swe-manager-study.sh
```

Install/verify the pinned upstream task dependencies:

```bash
bash scripts/agentic-jev/p7-prepare-swe-manager-study.sh
```

Then run the complete fixed paired cohort. The runner writes `run-start.json` before the first sample; preserve it together with any partial Inspect logs if execution fails:

```bash
bash scripts/agentic-jev/p7-run-swe-manager-paired.sh
```

Never delete or reuse a non-empty run root. A failed or partial attempt remains evidence; use a fresh `AGENTIC_JEV_SWE_MANAGER_RUN_ROOT` after a material repair.

## Claim boundary

A completed run may support a within-cohort paired estimate of the effect of **live Jev availability** under this exact Luna/runtime/skill/task configuration.

It does not establish:

- that Jev is universally beneficial;
- that a Jev-aligned answer is correct;
- effectiveness on other coding benchmarks or models;
- causal effects among the self-selected subset where Luna chose to call Jev;
- access to or evaluation of private chain-of-thought.
