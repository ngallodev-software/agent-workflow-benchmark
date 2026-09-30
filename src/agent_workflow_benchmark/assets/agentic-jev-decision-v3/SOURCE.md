# Jev decision-support v3 benchmark derivative provenance

This treatment remains derived from:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `65b444965e48209860e353f2aa0e8d9dbe35d2ce`
- source path: `skills/jev-decision-support/SKILL.md`

v3 preserves the public skill's three advertised semantic uses:

1. choose among plausible alternatives;
2. judge evidence sufficiency;
3. assess semantic risk.

The v2 benchmark adaptation over-constrained those uses by requiring deterministic
evidence to have failed to identify a single answer before *any* Jev call. That
allowed Choice on unresolved trade-offs but suppressed evidence-sufficiency and
risk checks once the coding agent formed a tentative leader.

v3 corrects that treatment boundary without weakening deterministic authority:

- exact rules/tests/specifications still control;
- an exactly resolved decision with no material semantic uncertainty does not call Jev;
- unresolved viable alternatives may use Choice;
- a tentative leader may use Noul for evidence sufficiency and/or Score for
  qualitative risk when those questions remain consequential and are not exactly
  determined.

Benchmark transport remains host-bridge-only through `jev_system_one`. No SDK,
direct HTTP path, or sandbox credential access is added.
