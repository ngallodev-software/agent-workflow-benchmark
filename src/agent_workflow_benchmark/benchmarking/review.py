from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, utc_now, validate_id
from .common import canonical_json_sha256, read_object, write_manifest
from .contracts import (
    BENCHMARK_HUMAN_REVIEW_SCHEMA,
    BENCHMARK_REVIEW_ASSIGNMENT_SCHEMA,
    validate_spec,
    validate_value,
)
from .events import append_event
from .live_review import live_url_for


def _stage_blinded_visuals(arm_dir: Path, destination: Path) -> list[str]:
    """Copy reviewable evidence into a label-only namespace.

    Returning paths from the consolidated arm directory would disclose the treatment
    through ``control_raw`` / ``workflow_full`` path segments. Copies also prevent a
    reviewer from resolving a symlink back to the unblinded source.
    """
    visual = arm_dir / "visual"
    if not visual.is_dir():
        return []
    destination.mkdir(parents=True, exist_ok=False)
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".html"}
    staged: list[str] = []
    for source in sorted(visual.iterdir()):
        if not source.is_file() or source.suffix.lower() not in allowed:
            continue
        target = destination / source.name
        shutil.copy2(source, target)
        staged.append(str(target))
    return staged


def _refresh_assignment_live_urls(
    plan: dict[str, Any], assignment_path: Path, mapping_path: Path
) -> bool:
    """Refresh review conveniences without changing the blinded label mapping."""
    if not mapping_path.is_file():
        return False
    assignment = read_object(assignment_path)
    mapping = read_object(mapping_path)
    labels_by_pair = {
        str(item["pair_id"]): item["labels"]
        for item in mapping.get("mappings", [])
        if isinstance(item, dict) and isinstance(item.get("labels"), dict)
    }
    changed = False
    for pair in assignment.get("pairs", []):
        if not isinstance(pair, dict):
            continue
        pair_id = str(pair.get("pair_id") or "")
        labels = labels_by_pair.get(pair_id)
        if not isinstance(labels, dict):
            continue
        assignment_labels = pair.get("labels")
        if not isinstance(assignment_labels, dict):
            continue
        for label in ("left", "right"):
            arm = labels.get(label)
            value = assignment_labels.get(label)
            if not isinstance(arm, str) or not isinstance(value, dict):
                continue
            current = live_url_for(plan, pair_id, arm)
            if value.get("live_url") != current:
                value["live_url"] = current
                changed = True
    if changed:
        validate_value(assignment, BENCHMARK_REVIEW_ASSIGNMENT_SCHEMA, "benchmark review assignment")
        atomic_write_json(assignment_path, assignment)
    return changed


def prepare_assignment(plan_path: Path, reviewer: str) -> dict[str, Any]:
    reviewer = validate_id(reviewer, "reviewer ID")
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    spec = validate_spec(Path(plan["coordinator"]["spec_path"]))
    root = run_dir / "human-review" / "assignments" / reviewer
    if root.exists():
        assignment = root / "assignment.json"
        if assignment.is_file():
            mapping = run_dir / "human-review" / ".blinding" / f"{reviewer}.json"
            refreshed = _refresh_assignment_live_urls(plan, assignment, mapping)
            if refreshed:
                write_manifest(run_dir)
            return {
                "reviewer": reviewer,
                "assignment": str(assignment),
                "existing": True,
                "live_urls_refreshed": refreshed,
            }
        raise WorkflowError(f"review assignment directory already exists: {root}")
    root.mkdir(parents=True)
    blind_root = run_dir / "human-review" / ".blinding"
    blind_root.mkdir(parents=True, exist_ok=True)
    assignments: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for pair in plan["pairs"]:
        order = ["control_raw", "workflow_full"]
        if secrets.randbits(1):
            order.reverse()
        labels = {"left": order[0], "right": order[1]}
        pair_dir = run_dir / "pairs" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}"
        assignment_labels: dict[str, Any] = {}
        for label, arm in labels.items():
            evidence_dir = root / "evidence" / str(pair["pair_id"]) / label
            files = _stage_blinded_visuals(pair_dir / arm, evidence_dir)
            assignment_labels[label] = {
                "evidence": files,
                "evidence_sha256": canonical_json_sha256(files),
                "live_url": live_url_for(plan, str(pair["pair_id"]), arm),
            }
        assignments.append(
            {
                "pair_id": pair["pair_id"],
                "case_id": pair["case_id"],
                "repetition": pair["repetition"],
                "labels": assignment_labels,
            }
        )
        mappings.append({"pair_id": pair["pair_id"], "labels": labels})
    rubric_path = Path(plan["coordinator"]["suite_dir"]) / spec["visual"]["rubric_path"]
    rubric = read_object(rubric_path)
    assignment_value = {
        "schema": BENCHMARK_REVIEW_ASSIGNMENT_SCHEMA,
        "run_id": plan["run_id"],
        "benchmark_id": plan["benchmark_id"],
        "reviewer_id": reviewer,
        "created_at": utc_now(),
        "blinded": True,
        "rubric": rubric,
        "pairs": assignments,
    }
    validate_value(assignment_value, BENCHMARK_REVIEW_ASSIGNMENT_SCHEMA, "benchmark review assignment")
    atomic_write_json(root / "assignment.json", assignment_value)
    template = {
        "schema": BENCHMARK_HUMAN_REVIEW_SCHEMA,
        "run_id": plan["run_id"],
        "benchmark_id": plan["benchmark_id"],
        "reviewer_id": reviewer,
        "submitted_at": None,
        "review_started_at": None,
        "review_completed_at": None,
        "active_review_seconds": None,
        "pairs": [
            {
                "pair_id": item["pair_id"],
                "scores": {
                    label: {dimension["id"]: None for dimension in rubric["dimensions"]}
                    for label in ("left", "right")
                },
                "preference": None,
                "confidence": None,
                "blocking_defects": [],
                "comments": [],
            }
            for item in assignments
        ],
    }
    atomic_write_json(root / "review-template.json", template)
    atomic_write_json(
        blind_root / f"{reviewer}.json",
        {
            "run_id": plan["run_id"],
            "reviewer_id": reviewer,
            "mappings": mappings,
            "created_at": utc_now(),
        },
        mode=0o600,
    )
    append_event(
        run_dir,
        event_type="human_review_assigned",
        run_id=str(plan["run_id"]),
        payload={"reviewer": reviewer, "pairs": len(assignments)},
    )
    write_manifest(run_dir)
    return {
        "reviewer": reviewer,
        "assignment": str(root / "assignment.json"),
        "review_template": str(root / "review-template.json"),
        "existing": False,
    }


def _unblind_blocking_defects(
    defects: object, labels: dict[str, str], pair_id: str
) -> list[dict[str, str]]:
    if not isinstance(defects, list):
        raise WorkflowError(f"blocking_defects for {pair_id} must be an array")
    result: list[dict[str, str]] = []
    for defect in defects:
        if isinstance(defect, str):
            description = defect.strip()
            if not description:
                raise WorkflowError(f"blocking defect for {pair_id} must not be empty")
            for arm in sorted(set(labels.values())):
                result.append({"arm": arm, "description": description})
            continue
        if not isinstance(defect, dict):
            raise WorkflowError(f"blocking defect for {pair_id} must be a string or object")
        label = defect.get("label")
        description = defect.get("description")
        if label not in {"left", "right", "both"}:
            raise WorkflowError(
                f"blocking defect label for {pair_id} must be left, right, or both"
            )
        if not isinstance(description, str) or not description.strip():
            raise WorkflowError(f"blocking defect description for {pair_id} is required")
        selected = labels.values() if label == "both" else (labels[label],)
        for arm in sorted(set(selected)):
            result.append({"arm": arm, "description": description.strip()})
    return result


def _require_exact_pair_ids(items: object, expected: set[str]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise WorkflowError("review pairs must be an array")
    pair_ids = [item.get("pair_id") for item in items if isinstance(item, dict)]
    if len(pair_ids) != len(items) or len(pair_ids) != len(set(pair_ids)):
        raise WorkflowError("review must contain unique pair IDs")
    if set(pair_ids) != expected:
        missing = sorted(expected - set(pair_ids))
        extra = sorted(set(pair_ids) - expected)
        raise WorkflowError(f"review pair set mismatch: missing={missing}; extra={extra}")
    return items


def _score_label(scores: dict[str, Any], rubric: dict[str, Any]) -> float:
    total = 0.0
    for dimension in rubric["dimensions"]:
        rating = scores.get(dimension["id"])
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise WorkflowError(
                f"review dimension {dimension['id']} must be an integer from 1 to 5"
            )
        total += float(dimension["weight"]) * ((rating - 1) / 4.0)
    return round(total, 4)


def submit_review(plan_path: Path, reviewer: str, input_path: Path) -> dict[str, Any]:
    reviewer = validate_id(reviewer, "reviewer ID")
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    spec = validate_spec(Path(plan["coordinator"]["spec_path"]))
    rubric = read_object(Path(plan["coordinator"]["suite_dir"]) / spec["visual"]["rubric_path"])
    mapping_path = run_dir / "human-review" / ".blinding" / f"{reviewer}.json"
    if not mapping_path.is_file():
        raise WorkflowError(f"reviewer has no blinded assignment: {reviewer}")
    mapping = read_object(mapping_path)
    submitted = read_object(input_path.resolve())
    submitted["schema"] = BENCHMARK_HUMAN_REVIEW_SCHEMA
    submitted["run_id"] = plan["run_id"]
    submitted["benchmark_id"] = plan["benchmark_id"]
    submitted["reviewer_id"] = reviewer
    submitted["submitted_at"] = utc_now()
    by_pair = {item["pair_id"]: item["labels"] for item in mapping["mappings"]}
    unblinded: list[dict[str, Any]] = []
    submitted_pairs = _require_exact_pair_ids(submitted.get("pairs"), set(by_pair))
    for item in submitted_pairs:
        pair_id = item.get("pair_id")
        if pair_id not in by_pair:
            raise WorkflowError(f"review references unassigned pair: {pair_id}")
        preference = item.get("preference")
        if preference not in {"left", "right", "tie", "neither"}:
            raise WorkflowError(f"invalid visual preference for {pair_id}: {preference}")
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, int) or not 1 <= confidence <= 5:
            raise WorkflowError(f"review confidence for {pair_id} must be 1..5")
        label_scores = item.get("scores")
        if not isinstance(label_scores, dict):
            raise WorkflowError(f"review scores missing for {pair_id}")
        computed = {label: _score_label(label_scores.get(label, {}), rubric) for label in ("left", "right")}
        item["computed_visual_scores"] = computed
        arm_scores = {by_pair[pair_id][label]: score for label, score in computed.items()}
        unblinded.append(
            {
                "pair_id": pair_id,
                "arm_scores": arm_scores,
                "preference_arm": by_pair[pair_id].get(preference) if preference in {"left", "right"} else preference,
                "confidence": confidence,
                "blocking_defects": _unblind_blocking_defects(
                    item.get("blocking_defects", []), by_pair[pair_id], str(pair_id)
                ),
            }
        )
    validate_value(submitted, BENCHMARK_HUMAN_REVIEW_SCHEMA, "benchmark human review")
    review_path = run_dir / "human-review" / "reviews" / f"{reviewer}.json"
    if review_path.exists():
        raise WorkflowError(f"review is immutable and already exists: {review_path}")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(review_path, submitted)
    private_path = run_dir / "human-review" / ".blinding" / f"{reviewer}-unblinded.json"
    atomic_write_json(
        private_path,
        {
            "run_id": plan["run_id"],
            "reviewer_id": reviewer,
            "results": unblinded,
            "submitted_at": submitted["submitted_at"],
        },
        mode=0o600,
    )
    append_event(
        run_dir,
        event_type="human_review_submitted",
        run_id=str(plan["run_id"]),
        payload={"reviewer": reviewer, "pairs": len(unblinded)},
    )
    write_manifest(run_dir)
    return {"reviewer": reviewer, "review": str(review_path), "pairs": len(unblinded)}
