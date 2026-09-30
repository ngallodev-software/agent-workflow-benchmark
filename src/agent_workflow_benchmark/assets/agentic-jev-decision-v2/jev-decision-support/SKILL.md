---
name: jev-decision-support
description: >
  Use when you, the coding agent, must make a bounded semantic judgment among
  multiple plausible alternatives and the Jev bridged tool is available. Typical
  triggers include choosing among implementation proposals, resolving ambiguous
  intent or interaction policy, judging evidence sufficiency, or comparing
  semantic risk. Do not use for deterministic facts, exact lookups, tests,
  calculations, or routine execution.
---

# Jev decision support

This skill is for **your own bounded decisions while solving a task**. It is not a
guide for adding TypeSafe or Jev to the product you are editing.

The available host-side Jev tool is named `jev_system_one` and may appear with a
`jev` MCP/tool prefix. It accepts bounded JSON `state`, typed `questions`, and
an optional short `purpose`.

## Decision gate

Before finalizing a consequential semantic choice, ask:

1. Is there more than one plausible option?
2. Have deterministic repository evidence, tests, specifications, or exact policy
   failed to identify a single answer?
3. Would the choice materially affect the implementation, review, UX, behavior,
   evidence interpretation, or risk?

If all three are true and `jev_system_one` is available, call it once before
finalizing the choice.

A task that explicitly presents competing implementation proposals is a canonical
`choice` opportunity unless deterministic evidence proves one proposal correct.

Do not call Jev merely because it is available. Prefer ordinary inspection for
facts and rules. Do not use Jev to run code, fetch files, calculate values, or
replace a test.

## Build the call

Collect the deterministic evidence first. Put only the evidence needed for the
judgment in `state`. Never include credentials or secrets.

Every question needs:

- a unique ID;
- `type`;
- non-empty `instructions`.

`choice` and `score` questions also need `criteria`.

### Choice

Use `choice` when exactly one option should be selected.

For proposal selection, make each proposal a criterion with a short stable key and
a concise meaning. Put the fuller proposal text and relevant repository evidence in
`state`.

Example shape:

~~~json
{
  "state": {
    "issue": "What behavior must be preserved",
    "repo_evidence": ["fact one", "fact two"],
    "proposals": {
      "proposal_1": "summary",
      "proposal_2": "summary"
    }
  },
  "questions": {
    "best_proposal": {
      "type": "choice",
      "instructions": "Choose the proposal that best satisfies the issue and repository evidence.",
      "criteria": {
        "proposal_1": "first implementation proposal",
        "proposal_2": "second implementation proposal"
      }
    }
  },
  "purpose": "Select among plausible implementation proposals after deterministic inspection."
}
~~~

### Noul

Use `noul` for a bounded yes/no semantic condition, such as whether the available
evidence is sufficient to act.

### Score

Use `score` for an ordered semantic dimension such as implementation risk or
evidence strength. Define concrete ordered levels.

## Use the result

Treat the Jev result as one typed judgment, not as authority over deterministic
evidence. Reconcile it with the facts you already inspected.

If Jev selects an option contradicted by an exact specification, test, or invariant,
follow the deterministic authority and note the disagreement in your reasoning.

Normally make at most one Jev call for a decision seam. A second call is justified
only when the first answer causes you to obtain materially new evidence or construct
a genuinely new choice.
