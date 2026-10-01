# Jev decision-support benchmark derivative v4 provenance

This source-synchronized benchmark skill is derived from:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `d0ac1ef45d1b79b18b2905872c62cb9e68d961c7`
- source path: `skills/jev-decision-support/SKILL.md`
- source skill Git blob: `ad6e00a2346ddf15009ad5119310cff3388ff8a2`
- source OpenAI metadata Git blob: `ba931acbdbdd7e1f8327db63f93468e396672d14`
- source helper Git blob: `bb28c18553cb9bebd3d4894e06ef587e8e04c47c`

This is a new benchmark derivative. It does **not** modify the frozen v2/v3 skill
assets that produced observed evidence.

The derivative carries forward the source update's substantive guidance:

- review context should include verbatim requirement text when available;
- include the candidate diff/artifact plus unchanged code it depends on;
- include deterministic tool output verbatim with explicit scope and omissions;
- keep the coding agent's preferred answer/confidence out of neutral evidence state;
- treat other-agent notes/verdicts as claims rather than tool output;
- exclude prior Jev answers by default to avoid anchoring;
- label unavoidable agent-only observations with source and basis;
- isolate agent-authored proposal evaluation from unrelated semantic questions;
- batch only related Choice/Noul/Score judgments that should share the same neutral
  primary-evidence context;
- every requested answer remains decision evidence;
- close distributions are split evidence, not strong decisions;
- evidence should be projected to fit limits rather than silently truncated;
- controlled evidence shows projected context can move distributions materially;
- sharper semantic distributions are not evidence of correctness and do not replace
  tests/type checking/linters;
- context/question ordering should be stable when comparing calls because key-order
  changes alone produced material probability shifts in the source experiment.

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
benchmark execution path. The upstream helper now accepts two-decimal probability
rounding using a per-option tolerance. The benchmark host bridge does not apply the
former strict sum-to-one check, and a regression test covers a 0.99-summing live-like
distribution. The benchmark already owns an independently validated host bridge,
redaction boundary, receipt ledger, and failure semantics.
