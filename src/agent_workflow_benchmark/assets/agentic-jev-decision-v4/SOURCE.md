# Jev decision-support benchmark derivative v4 provenance

This source-synchronized benchmark skill is derived from:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `627e508fb8798f66c4bae180b432c30dbe44570e`
- source path: `skills/jev-decision-support/SKILL.md`
- source skill Git blob: `840a1dd3aebeccbf17d1363a44665f1e2097492d`
- source OpenAI metadata Git blob: `ba931acbdbdd7e1f8327db63f93468e396672d14`

This is a new benchmark derivative. It does **not** modify the frozen v2/v3 skill
assets that produced observed evidence.

The derivative carries forward the source update's substantive guidance:

- review context should include verbatim requirement text when available;
- include the candidate diff/proposal plus unchanged code it depends on;
- include verification results with explicit scope and omissions;
- when repeating a semantic decision after new evidence, include the prior Jev answer
  and describe what materially changed;
- related Choice/Noul/Score judgments should be batched in one validated request;
- every requested answer remains decision evidence;
- close distributions are split evidence, not strong decisions;
- evidence should be projected to fit limits rather than silently truncated.

Benchmark-specific hardening remains intentionally different from the standalone
skill:

1. live inference is host-bridge-only through `jev_system_one`;
2. the standalone SDK helper and isolated `uv` runtime are not copied into the
   benchmark treatment;
3. the coding-agent sandbox must not install/import `typesafe-sdk`, call TypeSafe
   directly, request credentials, or search the filesystem for them;
4. benchmark host limits remain authoritative: 16 questions, 64 KiB normalized
   state, 48 KiB normalized questions;
5. host receipts remain authoritative execution evidence;
6. TypeSafe/Jev remains semantic evidence, not workflow authority.

The source repository's helper improvements are relevant provenance but are not a
benchmark execution path. The benchmark already owns an independently validated host
bridge, redaction boundary, receipt ledger, and failure semantics.
