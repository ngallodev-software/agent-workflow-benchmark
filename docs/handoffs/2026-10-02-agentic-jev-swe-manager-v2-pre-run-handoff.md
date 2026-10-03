# Agentic-Jev SWE-Lancer manager v2 — pre-run handoff

Continue from the merged Phase 9 preregistration for
`agentic-jev-swe-manager-v2`.

Preserve these boundaries:

- do not modify v1 evidence or v1/v4 treatment semantics;
- do not inspect SWE-Lancer correct-proposal/gold fields before or during inference;
- exclude all 36 IDs in the committed observed-manager registry;
- freeze exactly 30 fresh pairs using the v2 salt;
- treatment is the qualified deterministic manager request policy + live
  `jev_manager_decision`; control has the same skill/model without the live tool;
- official SWE-Lancer scorer is the sole correctness authority;
- both arms execute before score evidence is read;
- treatment no-call cases remain in the ITT denominator;
- called-only subsets are descriptive;
- preserve partial/failed runs and use a fresh run root after repairs;
- publish only through the sanitized v2 publication preparer.

Before execution verify repository HEAD, benchmark package 0.6.9, comparative-eval
0.3.4, Agent-Workflow 0.12.0, Inspect AI 0.3.268, Inspect SWE 0.2.71,
TypeSafe SDK 0.6.0, the pinned Inspect Evals commit, the v6 skill hash, request
builder/policy hashes, qualification lock, and cohort hash.

Operator order:

~~~bash
bash scripts/agentic-jev/p9-freeze-swe-manager-v2-study.sh
bash scripts/agentic-jev/p9-prepare-swe-manager-v2-study.sh
bash scripts/agentic-jev/p9-run-swe-manager-v2-paired.sh
~~~

After a complete 30-pair run:

~~~bash
bash scripts/agentic-jev/p9-prepare-swe-manager-v2-publication.sh
~~~

Do not interpret interim scores or modify the frozen treatment after outcome
observation.
