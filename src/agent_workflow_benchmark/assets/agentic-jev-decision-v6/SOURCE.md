# Jev decision-support benchmark derivative v6 provenance

This study-specific derivative builds on benchmark v5 and the standalone
`jev-decision-support` source commit
`4688bdf38e95e65725f6c7def5307dd8db39a702`.

Benchmark v6 changes only the treatment-facing host-tool contract for the new
SWE-Lancer manager v2 effectiveness study:

- the treatment tool is `jev_manager_decision`, not the older generic
  `jev_system_one`;
- authoritative task title, description, and complete proposals are injected by the
  host policy and must not be manually summarized by the coding agent;
- repository evidence and verification scope remain agent-supplied;
- one live checkpoint is expected before final proposal submission when the tool is
  available;
- at most one changed revision is permitted after explicit insufficiency and
  materially new evidence;
- control remains the same skill without a live host tool.

This is additive. v4 remains the completed v1 study identity and v5 remains the
pre-study request-builder guidance generation.
