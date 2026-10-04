"""Exploratory Jev v2 right-seam replay mechanics.

This module operates only on retained v2 request evidence.  It deliberately does
not load SWE-Lancer gold data or select a fresh cohort.  Provider dispatch remains
an explicit operator action performed by the existing v2 request executor.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agent_workflow.errors import WorkflowError

from .agentic_jev_request_v2 import build_jev_request, sha256_json

MECHANISM_SCHEMA = "agent-workflow-benchmark/jev-right-seam/v1"
MANIFEST_SCHEMA = "agent-workflow-benchmark/jev-right-seam-replay-manifest/v1"
M0 = "m0-exact-first-call"
M1 = "m1-descriptive-choice"
M2 = "m2-selection-plus-sufficiency"
M3 = "m3-per-proposal-support"
M4 = "m4-orchestration-counterfactual"


def order_preserving_json(value: object) -> str:
    """Serialize without key sorting so dispatch order remains observable."""
    try:
        return json.dumps(
            value,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorkflowError("right-seam request contains a non-JSON value") from exc


def dispatch_sha256(value: object) -> str:
    return hashlib.sha256(order_preserving_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowError(f"{label} must be an object")
    return value


def _first_request(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    request = entry.get("request")
    if not isinstance(request, Mapping):
        raise WorkflowError("replay entry requires exact first-call request")
    state = request.get("state")
    questions = request.get("questions")
    if not isinstance(state, Mapping) or not state:
        raise WorkflowError("replay first-call request requires state")
    if not isinstance(questions, Mapping) or not questions:
        raise WorkflowError("replay first-call request requires questions")
    return request


def validate_replay_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a private retained-cohort manifest without consulting gold.

    Each entry contains the exact first-call request and its recorded semantic and
    dispatch hashes.  Gold/correct proposal fields are rejected so request-building
    code cannot accidentally gain access to them.
    """
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise WorkflowError(f"replay manifest schema must be {MANIFEST_SCHEMA}")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise WorkflowError("replay manifest requires entries")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    forbidden = {"gold", "correct", "correct_proposal", "gold_proposal", "manager_data"}
    for raw in entries:
        entry = _mapping(raw, "replay entry")
        lowered = {str(k).lower() for k in entry}
        leaked = sorted(lowered & forbidden)
        if leaked:
            raise WorkflowError("replay manifest contains gold-bearing fields: " + ", ".join(leaked))
        sample_id = str(entry.get("sample_id") or "").strip()
        if not sample_id or sample_id in seen:
            raise WorkflowError("replay sample_id must be non-empty and unique")
        seen.add(sample_id)
        request = _first_request(entry)
        semantic = sha256_json(request)
        dispatch = dispatch_sha256(request)
        expected_semantic = str(entry.get("semantic_sha256") or "")
        expected_dispatch = str(entry.get("dispatch_sha256") or "")
        if expected_semantic and expected_semantic != semantic:
            raise WorkflowError(f"{sample_id}: semantic hash mismatch")
        if expected_dispatch and expected_dispatch != dispatch:
            raise WorkflowError(f"{sample_id}: dispatch hash mismatch")
        normalized.append({
            "sample_id": sample_id,
            "request": dict(request),
            "semantic_sha256": semantic,
            "dispatch_sha256": dispatch,
            "recorded": dict(entry.get("recorded") or {}),
        })
    return {"schema": MANIFEST_SCHEMA, "entries": normalized}


def _proposal_ids(request: Mapping[str, Any]) -> list[str]:
    state = _mapping(request.get("state"), "request.state")
    authoritative = _mapping(state.get("authoritative_task"), "state.authoritative_task")
    proposals = _mapping(authoritative.get("proposals"), "authoritative_task.proposals")
    ids = [str(k) for k in proposals]
    if len(ids) < 2:
        raise WorkflowError("right-seam mechanism requires at least two proposals")
    return ids


def _purpose(entry: Mapping[str, Any]) -> str:
    value = entry.get("purpose")
    return str(value) if isinstance(value, str) and value.strip() else (
        "Select the best supplied SWE-Lancer manager proposal from the bounded evidence."
    )


def _model(request: Mapping[str, Any]) -> str | None:
    value = request.get("model")
    return str(value) if isinstance(value, str) and value.strip() else None


def _build(entry: Mapping[str, Any], mechanism: str, questions: Mapping[str, Any]) -> dict[str, Any]:
    source = _first_request(entry)
    state = _mapping(source.get("state"), "request.state")
    built = build_jev_request(
        state=state,
        questions=questions,
        purpose=_purpose(entry),
        model=_model(source),
        policy_id=f"swe-manager-right-seam/{mechanism}",
        transformation={"mechanism": mechanism, "source_first_call_dispatch_sha256": dispatch_sha256(source)},
    )
    request = _mapping(built.get("request"), "built.request")
    built["mechanism"] = mechanism
    built["semantic_content_sha256"] = sha256_json(request)
    built["dispatch_body_sha256"] = dispatch_sha256(request)
    return built


def build_m0(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize the exact archived first-call body; no semantic transformation."""
    source = dict(_first_request(entry))
    return {
        "schema": MECHANISM_SCHEMA,
        "mechanism": M0,
        "request": source,
        "semantic_content_sha256": sha256_json(source),
        "dispatch_body_sha256": dispatch_sha256(source),
        "exact_replay": True,
    }


def build_m1(entry: Mapping[str, Any]) -> dict[str, Any]:
    request = _first_request(entry)
    ids = _proposal_ids(request)
    criteria = {
        pid: (
            f"Select when authoritative_task.proposals.{pid} best satisfies the task "
            "requirement and supplied repository/verification evidence relative to "
            "the other official proposals."
        )
        for pid in ids
    }
    criteria["insufficient_evidence"] = (
        "The bounded supplied evidence does not justify selecting one official proposal."
    )
    questions = {
        "best_proposal": {
            "type": "choice",
            "instructions": (
                "Which supplied official proposal is best supported by the authoritative "
                "task requirement and bounded repository/verification evidence?"
            ),
            "criteria": criteria,
        },
        "evidence_sufficient": {
            "type": "noul",
            "instructions": "Is the bounded supplied evidence sufficient to make this proposal-selection decision?",
            "criteria": {"true": "Material evidence is present.", "false": "Material evidence is missing."},
        },
    }
    return _build(entry, M1, questions)


def build_m2(entry: Mapping[str, Any]) -> dict[str, Any]:
    request = _first_request(entry)
    ids = _proposal_ids(request)
    questions = {
        "best_proposal": {
            "type": "choice",
            "instructions": "Which supplied official proposal is best supported relative to the other supplied proposals?",
            "criteria": {
                pid: (
                    f"authoritative_task.proposals.{pid}; judge only its relative support "
                    "from the bounded task, repository, and verification evidence."
                )
                for pid in ids
            },
        },
        "evidence_sufficient": {
            "type": "noul",
            "instructions": "Is the bounded supplied evidence sufficient to act on the separate proposal-selection signal?",
            "criteria": {"true": "Sufficient for action.", "false": "Route to review without replacing the selection signal."},
        },
    }
    return _build(entry, M2, questions)


def build_m3(entry: Mapping[str, Any]) -> dict[str, Any]:
    request = _first_request(entry)
    ids = _proposal_ids(request)
    scale = [
        "0 — contradicted or unsupported by the bounded evidence.",
        "1 — weak support; important evidence is absent or adverse.",
        "2 — mixed support; material evidence exists on both sides.",
        "3 — strong support from the bounded requirement/repository/verification evidence.",
        "4 — very strong, direct support with no material bounded evidence against it.",
    ]
    questions = {
        f"support_for_{pid}": {
            "type": "score",
            "instructions": (
                f"How strongly do the authoritative requirement, repository evidence, "
                f"and explicit verification scope support authoritative_task.proposals.{pid} "
                "as an implementation choice? Use the common anchored scale exactly."
            ),
            "criteria": scale,
        }
        for pid in ids
    }
    return _build(entry, M3, questions)


def compose_m2(*, selection: str, sufficiency: float, threshold: float) -> dict[str, Any]:
    """Preserve first selection while code alone owns action routing."""
    if not 0.0 <= sufficiency <= 1.0 or not 0.0 <= threshold <= 1.0:
        raise WorkflowError("sufficiency and threshold must be within [0, 1]")
    if not selection.strip():
        raise WorkflowError("selection signal must be non-empty")
    return {
        "selection_signal": selection,
        "sufficiency_signal": sufficiency,
        "routing_threshold": threshold,
        "candidate": selection,
        "workflow_action": "candidate_selection" if sufficiency >= threshold else "review_required",
        "second_same_agent_jev_call": False,
    }


def compose_m3(scores: Mapping[str, float], *, tie_epsilon: float = 0.0) -> dict[str, Any]:
    """Rank parallel support evidence deterministically; Jev never breaks its own tie."""
    if not scores:
        raise WorkflowError("M3 requires proposal scores")
    if tie_epsilon < 0:
        raise WorkflowError("tie_epsilon must be non-negative")
    ordered = sorted(((str(k), float(v)) for k, v in scores.items()), key=lambda item: (-item[1], item[0]))
    top_id, top = ordered[0]
    tied = len(ordered) > 1 and abs(top - ordered[1][1]) <= tie_epsilon
    return {
        "ranking": [{"proposal_id": pid, "score": score} for pid, score in ordered],
        "candidate": top_id,
        "workflow_action": "review_required" if tied else "candidate_selection",
        "tie": tied,
        "tie_epsilon": tie_epsilon,
        "second_same_agent_jev_call": False,
    }


def m4_policies(*, first_choice: str, first_sufficiency: float, observed_final_choice: str | None = None, threshold: float = 0.50) -> dict[str, Any]:
    """Compute orchestration counterfactuals from frozen first-call evidence only."""
    preserved = compose_m2(selection=first_choice, sufficiency=first_sufficiency, threshold=threshold)
    return {
        "mechanism": M4,
        "first_choice": first_choice,
        "first_sufficiency": first_sufficiency,
        "observed_final_choice": observed_final_choice,
        "preserve_first": preserved,
        "choice_only": {"candidate": first_choice, "workflow_action": "candidate_selection"},
    }


def counterbalanced_ids(proposal_ids: Sequence[str], *, mechanism: str, sample_id: str) -> list[str]:
    """Deterministically rotate proposal order for the order-sensitivity arm."""
    ids = [str(v) for v in proposal_ids]
    if len(ids) < 2:
        return ids
    digest = hashlib.sha256(f"{mechanism}:{sample_id}".encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big") % len(ids)
    rotated = ids[offset:] + ids[:offset]
    if rotated == ids:
        rotated = list(reversed(ids))
    return rotated
