# Agentic Jev current-model context and rationale qualification

**Status:** qualification harness; no effectiveness claim  
**Skill:** source-synchronized v4 derivative from `jev-decision-support@d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`  
**Models:** GPT-6 Luna and GPT-6.1 Sol through the Codex-LB provider path

## Purpose

This is a small live qualification for the current coding-agent generation. It answers three narrow questions only:

1. Did the installed Jev decision-support skill cause a real host-side `jev_system_one` call on a genuine bounded semantic trade-off?
2. Did the request include the primary evidence the current skill says matters: verbatim requirement text, both candidate artifacts, unchanged dependent code, deterministic verification output, and verification omissions/scope?
3. Did the coding agent leave a bounded **observable decision justification** that can be audited later?

It does not score whether the selected proposal is correct and it does not request or export hidden chain-of-thought.

## Why this is separate from v2/v3

The v2/v3 assets and their runs are frozen evidence. This qualification uses the current v4 source-synchronized skill unchanged. The task contract, not the skill snapshot, requires a visible decision record so the benchmark can retain the agent's final justification without contaminating the Jev request.

## Fixture

The one-sample fixture supplies:

- `requirement.md` with the verbatim requirement source;
- `proposal_1.md` and `proposal_2.md` with two plausible designs;
- unchanged `src/cache.py` code the proposals depend on;
- `verification.txt` showing both prototypes pass 17/17 checks and explicitly naming what was not exercised.

No deterministic source ranks the two surviving candidates. The final choice is therefore a bounded semantic trade-off rather than an exact lookup.

The prompt does **not** name Jev or TypeSafe.

## Pass conditions

A qualification passes only when all of the following are true:

- exactly one host-side Jev receipt exists;
- exactly one receipt is successful;
- the TypeSafe API key is absent from the coding-agent transcript;
- the Jev state contains exact fixture anchors for the requirement, both proposals, unchanged dependency code, deterministic verification result, and verification scope/omissions;
- at least one Choice question is present;
- the tool purpose is nonempty;
- primary Jev state contains no benchmark-forbidden agent-verdict keys such as `preferred_option`, `selected_option`, or `initial_agent_choice`;
- Luna/Sol's final visible response is exactly one JSON decision record with:
  - `selected_option`;
  - an 80–1200 character observable `justification`;
  - at least three valid `evidence_refs`;
  - the decisive `tradeoff`;
  - `semantic_evidence_reconciliation` explaining how semantic evidence was weighed against primary evidence;
  - `remaining_uncertainty` or null.

The qualification artifact stores request/evidence hashes and pass/fail checks, not the raw private Jev context. The private host receipt remains the source for request inspection.

Reasoning-block count may be recorded as a diagnostic, but reasoning content is not exported and is not a pass condition. The required evidence is the visible bounded justification.

## Run Luna

~~~bash
source scripts/agentic-jev/env.sh
bash scripts/agentic-jev/p6-qualify-current-model.sh
~~~

The default model is:

~~~text
openai-api/codex-lb/gpt-6-luna
~~~

## Run GPT-6.1 Sol

~~~bash
AGENTIC_JEV_CURRENT_MODEL='openai-api/codex-lb/gpt-6.1-sol' \
  AGENTIC_JEV_CURRENT_QUAL_ROOT="$AGENTIC_JEV_ROOT/current-model-qualification/gpt-6.1-sol" \
  bash scripts/agentic-jev/p6-qualify-current-model.sh
~~~

Use a fresh output root for each run. `TYPESAFE_API_KEY` remains host-only and Codex-LB must be reachable from the Inspect host.

## Interpretation boundary

A pass establishes tool activation, fixture-complete context projection, and durable visible justification for one synthetic semantic decision. It does not establish Jev correctness, model correctness, generalization, or treatment effect.
