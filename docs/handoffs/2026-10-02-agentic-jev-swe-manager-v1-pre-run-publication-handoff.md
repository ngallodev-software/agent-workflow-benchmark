# Agentic-Jev SWE-Lancer manager v1 — pre-run/publication handoff

**Date:** 2026-10-02  
**Study:** `agentic-jev-swe-manager-v1`  
**State:** preregistered, implementation hardened, publication path prepared, **not run**  
**Operator boundary:** host-side cohort freeze, dependency preparation, and paired execution remain user/operator actions.

## Canonical repository anchors

Use these as the continuation point unless repository HEAD has moved. Always verify HEAD first and preserve newer work.

| Repository / source | Canonical anchor |
| --- | --- |
| `ngallodev-software/agent-workflow-benchmark@main` | `143d35e68c15c000bfebc49786d4d387f7ea7a1b` |
| `ngallodev-software/agent-workflow-comparative-eval@master` | `70e2ee9442426d556bc4209997572d10094cab58` |
| `ngallodev-software/agent-workflow@master` | `4254f48a456535515b8e9e65d6c4952f90575c74` |
| Jev decision-support source | `d0ac1ef45d1b79b18b2905872c62cb9e68d961c7` |
| Inspect Evals source pinned by the study | `190dfa27bc2e9b3e966ea6e8a682626d55b513c0` |

The original preregistration anchors remain historical provenance. The three repository anchors above supersede them for execution because all changes described here occurred before any Phase 7 cohort freeze or result observation.

## What changed before execution

### Comparative-eval 0.3.4

The provider-neutral paired-decision layer now:

- preserves the actual frozen cohort artifact SHA separately from the pair-key digest;
- rejects reports that mix source or runtime identities;
- preserves exact successful-call context-known/context-complete counts;
- preserves resolved Jev model identities from successful receipts;
- summarizes coding-agent latency/token overhead with paired treatment-minus-control statistics;
- reports host-side Jev receipt token and duration totals separately from coding-agent usage;
- records score-availability reliability counts;
- retains the original primary correctness semantics, four paired cells, exact McNemar result, and deterministic paired bootstrap.

Do not combine coding-agent tokens and Jev-service tokens into one token total across unlike models.

### Agent-Workflow comparative boundary

Agent-Workflow now accepts additive comparative-eval versions through 0.3.4 and its release gate actually executes the compatibility test. The earlier green PR had not exercised that top-level test because the release script only ran the acceptance/invariant/release directories; that gap is now closed.

No Agent-Workflow lifecycle or decision authority moved into comparative-eval.

### Benchmark pre-run hardening

The Phase 7 implementation now:

- fixes the original literal escaped shell expansions in all Phase 7 operator scripts;
- labels host-side Jev receipts with the Phase 7 study ID instead of the earlier pilot ID;
- writes validated `run-start.json` before the first paired task;
- binds benchmark git/source hashes, package versions, imported result-affecting module hashes, coding-agent runtime, requested Jev model, pinned Inspect source/scorer, and cohort identity;
- refuses tracked benchmark source drift at execution time;
- retains resolved Jev model identities from successful calls;
- preserves nested Inspect model usage rather than flattening it away;
- projects private Jev receipt service usage/duration into sanitized paired evidence;
- freezes/verifies `inspect-ai==0.3.268`, `inspect-swe==0.2.71`, `typesafe-sdk==0.6.0`, Agent-Workflow 0.12.0, and comparative-eval 0.3.4 during Phase 7 preparation;
- documents that hash-parity arm ordering is deterministic/outcome-blind but does not guarantee an exact 15/15 order split;
- re-audits freshness lineage: the later v2 manager run reused the same six external-scout manager IDs and the proposed v3 manager canary was retired, so the frozen prior external cohort currently covers all earlier official SWE-Lancer manager exposure;
- makes dollar cost explicitly unavailable in v1 because no authoritative provider billing schedule was frozen before execution.

None of those changes alters the cohort-selection rule, treatment definition, prompt contract, official scorer, intent-to-treat denominator, missing-score rule, primary estimand, exact McNemar test, or paired-bootstrap method.

## Publication seam now exists

Benchmark 0.6.7 adds a Phase 7 publication preparer and verifier:

```bash
bash scripts/agentic-jev/p7-prepare-swe-manager-publication.sh
```

Run it **only after a complete 30-pair run**.

The publication gate:

1. validates the completed run and all 30 public-safe paired trial records;
2. recomputes the paired report from those trials and requires exact agreement with the stored report;
3. requires official SWE-Lancer scoring, the paired outcome-read barrier, and successful credential-absence checks;
4. strips private/local runtime paths such as Codex cache paths;
5. hashes rather than copies Inspect logs, raw Jev receipt files, and the private run-start artifact;
6. scans the generated tree for the active API-key value, the private run-root path, and common local user-home paths;
7. writes and re-verifies `MANIFEST.sha256`;
8. supports independent verification of the copied public bundle from the allowlisted files alone.

The public bundle contains only:

```text
README.md
publication.json
metrics/paired-report.json
evidence/paired-trials.jsonl
evidence/private-artifact-hashes.json
MANIFEST.sha256
```

The paired trials preserve bounded visible decision evidence, applied proposal IDs, official binary scores, process/reliability evidence, timing/token data, request hashes, and Jev context-completeness aggregates. They do **not** contain raw Jev state/questions, provider HTTP payloads, credentials, Inspect logs, or hidden chain-of-thought.

## Frozen study semantics to preserve

- Upstream Inspect Evals `swe_manager` supplies the task, dataset, sandbox, and sole correctness scorer.
- Both arms use GPT-6 Luna/high and the same current Jev decision-support skill.
- Control has no live Jev bridge.
- Treatment has the host-side Jev bridge.
- The prompt does not require or name Jev; both arms are told to use installed skills when applicable.
- Target cohort: 30 fresh manager tasks selected by ascending `sha256("agentic-jev-swe-manager-v1:" + sample_id)` after excluding all previously observed manager IDs.
- Do not inspect or use correct-proposal/gold fields for selection, prompting, stopping, or exclusion.
- Primary estimand: treatment attempt accuracy minus control attempt accuracy across all frozen pairs.
- Missing/non-binary official arm score counts incorrect at attempt level.
- Treatment no-call tasks remain in the treatment denominator.
- Called-only and successful-call-only subsets are descriptive/self-selected only.
- Report point estimate, paired interval, four correctness cells, exact McNemar result, Jev exposure/context evidence, visible justification/reconciliation coverage, reliability/process evidence, overhead, and limitations together.
- Semantic agreement with Jev is never correctness.
- Do not request or expose hidden chain-of-thought.

## Operator sequence — unchanged

Do not execute these from a repository-stewardship agent unless the user explicitly asks for host-side study execution.

```bash
bash scripts/agentic-jev/p7-freeze-swe-manager-study.sh
bash scripts/agentic-jev/p7-prepare-swe-manager-study.sh
bash scripts/agentic-jev/p7-run-swe-manager-paired.sh
```

After a complete run:

```bash
bash scripts/agentic-jev/p7-prepare-swe-manager-publication.sh
```

A failed or partial run is evidence. Do not delete it or retry into the same non-empty run root. Preserve `run-start.json`, Inspect logs, and any receipts, diagnose the failure without outcome-dependent exclusions, and use a fresh run root only after a material repair.

## When results arrive

Before interpreting effectiveness:

1. verify the run used the exact frozen cohort artifact and pinned Inspect Evals commit/scorer hash;
2. verify the benchmark commit/runner/bridge/module hashes and package versions from `run-start.json`;
3. verify the skill commit/hash, coding-agent model/effort, Codex version, requested Jev model, and resolved Jev model identities;
4. verify all 30 paired trials exist and the stored paired report reproduces exactly from them;
5. verify official score availability/failure handling followed the preregistered attempt-level rule;
6. verify no outcome-dependent stopping or post-hoc silent pair exclusion occurred;
7. inspect Jev exposure/context-completeness and visible decision-evidence coverage as process evidence, not correctness;
8. interpret called-only subsets descriptively only;
9. report the primary effect together with its paired interval, discordant counts, McNemar result, reliability/overhead, and the n=30 limitation;
10. prepare and independently verify the public bundle before moving anything into `agent-workflow-benchmark-results`, the portfolio, or lab-note/public timeline surfaces.

## Public-writing boundary

No effectiveness claim exists yet. Until a complete validated paired run is supplied, public-facing material should describe this as a preregistered effectiveness study with hardened execution/evidence/publication machinery, not as evidence that Jev improves or harms SWE-Lancer performance.
