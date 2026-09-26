#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aw_require_executable "$PYTHON"
aw_require_file "$RESOLUTION_REVIEW"

"$PYTHON" - "$RESOLUTION_REVIEW" "$RESOLUTION_REVIEW_MD" "${ORACLE_REVIEW_GUIDE:-}" <<'PY'
import json
import sys
from pathlib import Path

review_path = Path(sys.argv[1])
markdown_path = Path(sys.argv[2])
guide_path = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None

with review_path.open(encoding="utf-8") as handle:
    review = json.load(handle)

QUESTIONS = {
    "routing.task_class": "What is the primary requested deliverable of this case?",
    "routing.interaction_required": (
        "Is a material user decision, authorization, or preference missing from "
        "the supplied state and required before the requested action can be "
        "completed responsibly?"
    ),
    "routing.semantic_risk": (
        "What is the consequence of acting on a materially wrong interpretation "
        "of this request?"
    ),
}

def scalar(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)

def rubric_lines(conflict):
    seam = conflict.get("decision_seam") or {}
    decision_id = conflict.get("decision_id")

    if decision_id == "routing.semantic_risk":
        meanings = seam.get("level_meaning") or {}
        lines = [
            "Judge semantic consequence, not generic code complexity.",
        ]
        for level in seam.get("levels") or [0, 1, 2]:
            meaning = meanings.get(str(level))
            if not meaning:
                defaults = {
                    0: "low consequence; local/easily reversible work",
                    1: "moderate consequence; meaningful but recoverable impact",
                    2: "high consequence; production, security, credentials, public claims, destructive/irreversible state, or another high-impact boundary",
                }
                meaning = defaults.get(level, "")
            lines.append(f"- **{level}** — {meaning}")
        return lines

    if decision_id == "routing.task_class":
        meanings = seam.get("label_meaning") or {}
        labels = seam.get("labels") or [
            "implementation", "diagnosis", "review", "documentation", "other"
        ]
        lines = [f"- **{label}** — {meanings.get(label, '')}" for label in labels]
        precedence = seam.get("mixed_intent_precedence") or []
        if precedence:
            lines += ["", "Mixed-intent precedence:"]
            lines += [f"- {item}" for item in precedence]
        return lines

    if decision_id == "routing.interaction_required":
        proposition = seam.get("proposition") or (
            "A material user decision, authorization, or preference is missing "
            "and required before responsible completion."
        )
        lines = [
            f"- **true** — {proposition}",
            "- **false** — the case can responsibly proceed without such a missing external choice or authorization.",
        ]
        true_when = seam.get("true_when") or []
        false_when = seam.get("false_when") or []
        if true_when:
            lines += ["", "Typical **true** conditions:"]
            lines += [f"- {item}" for item in true_when]
        if false_when:
            lines += ["", "Typical **false** conditions:"]
            lines += [f"- {item}" for item in false_when]
        return lines

    return [f"Allowed labels: {conflict.get('allowed_labels')!r}"]

conflicts = review.get("three_way_conflicts") or []
lines = [
    "# Three-way oracle resolution review",
    "",
    "This is the human-facing rendering of the private machine review artifact.",
    "",
    "**Important:** `oracle_eligible` means a seam requires an oracle label. It is not the label itself. "
    "Metadata is evidence, not ground truth.",
    "",
    "Use only the verbatim case prompt, supplied metadata, frozen rubric, and independent A/B/C votes. "
    "Do not add facts from the live repository, deployment environment, credentials, portfolio site, or other private context unless they appear in the frozen case.",
    "",
    f"Study: `{review.get('study_id', '')}`  ",
    f"Dataset: `{review.get('dataset_version', '')}`  ",
    f"Three-way conflicts: **{len(conflicts)}**",
    "",
]

if guide_path is not None:
    lines += [
        "## Reviewer references",
        "",
        f"- Reviewer guide: `{guide_path}`",
        "- The frozen oracle protocol remains authoritative.",
        "",
    ]

for index, conflict in enumerate(conflicts, 1):
    case_id = str(conflict.get("case_id", ""))
    decision_id = str(conflict.get("decision_id", ""))
    task = conflict.get("task") or "(missing case prompt)"
    question = conflict.get("oracle_question") or QUESTIONS.get(
        decision_id,
        f"What is the correct frozen-oracle label for {decision_id}?",
    )
    metadata = conflict.get("metadata") or {}
    votes = conflict.get("votes") or {}

    lines += [
        f"## {index}. {case_id} — `{decision_id}`",
        "",
        "### Verbatim case prompt",
        "",
        f"> {task}",
        "",
        "### Question you are deciding",
        "",
        f"**{question}**",
        "",
        "### Supplied metadata",
        "",
    ]
    if metadata:
        for key in sorted(metadata):
            lines.append(f"- `{key}`: `{scalar(metadata[key])}`")
    else:
        lines.append("- *(none supplied)*")

    lines += [
        "",
        "> Metadata is supporting evidence only. Do not copy `risk`, `task_type`, or "
        "`requires_interaction` directly into the oracle label.",
        "",
        "### Frozen rubric",
        "",
    ]
    lines += rubric_lines(conflict)
    lines += [
        "",
        "### Independent votes",
        "",
        f"- **A:** `{scalar(votes.get('a'))}`",
        f"- **B:** `{scalar(votes.get('b'))}`",
        f"- **C:** `{scalar(votes.get('c'))}`",
        "",
        "### Human resolution",
        "",
        "Record the final label, rationale, and participants in `resolutions.json`.",
        "",
        "- **Final label:** _pending_",
        "- **Rationale:** _pending_",
        "- **Participants:** _pending_",
        "",
        "---",
        "",
    ]

markdown_path.parent.mkdir(parents=True, exist_ok=True)
tmp = markdown_path.with_name(markdown_path.name + ".tmp")
tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
tmp.replace(markdown_path)
print(markdown_path)
PY

echo "Human review: $RESOLUTION_REVIEW_MD"
