from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

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


def _scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _rubric_lines(conflict: Mapping[str, Any]) -> list[str]:
    seam = conflict.get("decision_seam") or {}
    decision_id = conflict.get("decision_id")

    if decision_id == "routing.semantic_risk":
        meanings = seam.get("level_meaning") or {}
        lines = ["Judge semantic consequence, not generic code complexity."]
        for level in seam.get("levels") or [0, 1, 2]:
            meaning = meanings.get(str(level))
            if not meaning:
                defaults = {
                    0: "low consequence; local/easily reversible work",
                    1: "moderate consequence; meaningful but recoverable impact",
                    2: (
                        "high consequence; production, security, credentials, "
                        "public claims, destructive/irreversible state, or "
                        "another high-impact boundary"
                    ),
                }
                meaning = defaults.get(level, "")
            lines.append(f"- **{level}** — {meaning}")
        return lines

    if decision_id == "routing.task_class":
        meanings = seam.get("label_meaning") or {}
        labels = seam.get("labels") or [
            "implementation",
            "diagnosis",
            "review",
            "documentation",
            "other",
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
            (
                "- **false** — the case can responsibly proceed without such a "
                "missing external choice or authorization."
            ),
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


def render_resolution_review(
    review_path: Path,
    markdown_path: Path,
    guide_path: Path | None = None,
) -> Path:
    review_path = Path(review_path)
    markdown_path = Path(markdown_path)
    guide_path = Path(guide_path) if guide_path else None

    with review_path.open(encoding="utf-8") as handle:
        review = json.load(handle)
    if not isinstance(review, dict):
        raise ValueError(f"expected JSON object: {review_path}")

    conflicts = review.get("three_way_conflicts") or []
    lines = [
        "# Three-way oracle resolution review",
        "",
        "This is the human-facing rendering of the private machine review artifact.",
        "",
        (
            "**Important:** `oracle_eligible` means a seam requires an oracle "
            "label. It is not the label itself. Metadata is evidence, not ground truth."
        ),
        "",
        (
            "Use only the verbatim case prompt, supplied metadata, frozen rubric, "
            "independent A/B/C votes, and any structured A/B/C justifications "
            "rendered below. Do not add facts from the live repository, deployment "
            "environment, credentials, portfolio site, provider reasoning summaries, "
            "or other private context unless they appear in the frozen case."
        ),
        "",
        f"Study: `{review.get('study_id', '')}`  ",
        f"Dataset: `{review.get('dataset_version', '')}`  ",
        f"Three-way conflicts: **{len(conflicts)}**",
        "",
    ]

    if guide_path is not None and guide_path.is_file():
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
        justifications = conflict.get("justifications") or {}

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
                lines.append(f"- `{key}`: `{_scalar(metadata[key])}`")
        else:
            lines.append("- *(none supplied)*")

        lines += [
            "",
            (
                "> Metadata is supporting evidence only. Do not copy `risk`, "
                "`task_type`, or `requires_interaction` directly into the oracle label."
            ),
            "",
            "### Frozen rubric",
            "",
        ]
        lines += _rubric_lines(conflict)
        lines += [
            "",
            "### Independent votes",
            "",
            f"- **A:** `{_scalar(votes.get('a'))}`",
            f"- **B:** `{_scalar(votes.get('b'))}`",
            f"- **C:** `{_scalar(votes.get('c'))}`",
            "",
        ]

        if justifications:
            lines += [
                "### Independent structured justifications",
                "",
                (
                    "These are authoritative v2 decision-evidence fields from the "
                    "independent passes. They are not provider chain-of-thought or "
                    "reasoning summaries."
                ),
                "",
            ]
            for role in ("a", "b", "c"):
                justification = justifications.get(role)
                if not isinstance(justification, dict):
                    continue
                lines += [
                    f"#### {role.upper()}",
                    "",
                    f"- **Ambiguity:** `{_scalar(justification.get('ambiguity'))}`",
                    f"- **Rubric rule:** {justification.get('rubric_rule', '')}",
                    "- **Decisive case evidence:**",
                ]
                for item in justification.get("decisive_case_evidence") or []:
                    lines.append(f"  - {item}")
                lines.append("")

        lines += [
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
    return markdown_path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in {2, 3}:
        raise SystemExit(
            "usage: python -m agent_workflow_benchmark.benchmarking.resolution_review "
            "REVIEW_JSON REVIEW_MD [GUIDE]"
        )
    review_path = Path(args[0])
    markdown_path = Path(args[1])
    guide_path = Path(args[2]) if len(args) == 3 and args[2] else None
    rendered = render_resolution_review(review_path, markdown_path, guide_path)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
