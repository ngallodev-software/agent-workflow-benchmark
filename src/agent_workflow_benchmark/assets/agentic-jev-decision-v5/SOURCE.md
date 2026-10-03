# Jev decision-support benchmark derivative v5 provenance

This benchmark skill is derived from the current standalone decision-support skill:

- repository: `ngallodev-software/jev-decision-support`
- source commit: `4688bdf38e95e65725f6c7def5307dd8db39a702`
- source path: `skills/jev-decision-support/SKILL.md`
- source skill Git blob: `8cda894da2c83421a21d13c296d0f71e4742916d`
- source OpenAI metadata Git blob: `481204922312cee343323181a06788db29ecbc6e`
- source helper Git blob: `f5c24b6349c3240c10efa901a38d078c91e44073`

The source update was informed by the current TypeSafe System One agent skill and
official SDK request schemas. The relevant design rules are:

- put enough relevant state around each judgment and use named JSON fields when the
  state has distinct roles;
- question IDs are response keys, not instructions;
- Choice criteria define the available candidates, so omitted candidates cannot be
  selected;
- batch independent questions that share state because System One evaluates them in
  parallel and they cannot consume one another's answers;
- make a second semantic request only when an earlier answer is needed to fetch
  evidence, construct changed state, or determine a changed option set;
- do not interpret low Choice/Score confidence as proof that context is missing;
- keep policy and deterministic workflow logic in code around the typed judgments.

The standalone source now includes a deterministic `buildJevRequest` /
`executeJevRequest` / `rebuildJevRequest` helper path with canonical hashes,
local structural/size validation, mutation detection, and unchanged-revision
rejection. That local SDK helper is **not** copied into the benchmark treatment.

Benchmark-specific differences remain intentional:

1. live inference is host-bridge-only through `jev_system_one`;
2. the coding-agent sandbox must not install/import `typesafe-sdk`, call TypeSafe
   directly, request credentials, or create another network path;
3. benchmark host limits remain authoritative: at most 16 questions, 64 KiB
   normalized state, and 48 KiB normalized questions;
4. private host receipts remain the authoritative provider-dispatch history;
5. generic host validation owns request shape/privacy/identity, while a
   task-specific deterministic adapter must own semantic completeness;
6. subsequent semantic calls are valid only after materially changed evidence,
   alternatives, or requirements; future versioned adapters should retain the prior
   request/decision identity and a machine-readable change reason;
7. Jev remains advisory semantic evidence; deterministic requirements, tests,
   validation, permissions, and workflow state remain authoritative.

This v5 derivative is additive. It does **not** modify the v4 asset or
`agentic_jev_decision_v4.py` used by the completed
`agentic-jev-swe-manager-v1` study.
