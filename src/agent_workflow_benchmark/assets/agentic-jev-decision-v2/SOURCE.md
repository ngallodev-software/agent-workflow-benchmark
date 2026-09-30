# Jev decision-support benchmark derivative provenance

This benchmark skill is derived from:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `65b444965e48209860e353f2aa0e8d9dbe35d2ce`
- source path: `skills/jev-decision-support/SKILL.md`
- source skill blob at that commit: `4ad10f1ff167cf9a9a110bca1d7abab19c870386`

The benchmark derivative preserves the source skill's core structure and semantics:

- agent-side decision support rather than product integration;
- evidence-first bounded semantic judgment;
- Choice, Noul, and Score guidance;
- context projection and privacy discipline;
- deterministic authority over semantic advice;
- no unchanged retries to seek a preferred answer;
- tool use is not an effectiveness claim.

Benchmark-specific hardening:

1. live inference is **host-bridge only** through `jev_system_one`;
2. direct SDK installation/import, direct HTTP calls, helper execution, and credential
   acquisition are prohibited inside the coding-agent sandbox;
3. limits mirror the benchmark host validator: 16 questions, 64 KiB state,
   48 KiB questions;
4. one-call-per-decision-seam discipline is explicit;
5. host receipts remain the authoritative execution evidence.

The source repository's `scripts/jev_decision.py` helper is intentionally **not
copied into this benchmark skill directory**. It is appropriate for the standalone
public skill, but providing a second live transport inside this treatment would
weaken credential isolation and make Jev execution accounting ambiguous.
