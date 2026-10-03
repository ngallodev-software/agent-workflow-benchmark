"""SWE-Lancer manager policy adapter for the deterministic Jev request builder v2."""
from __future__ import annotations

import asyncio
import csv
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import sha256_file

from .agentic_jev_request_v2 import (
    build_jev_request,
    execute_built_jev_request,
    sha256_json,
)

POLICY_ID = "swe-manager-choice-v2"
POLICY_VERSION = "2.0.0"
QUALIFICATION_SAMPLE_ID = "18796-manager-0"
EVIDENCE_SUFFICIENCY_REBUILD_THRESHOLD = 0.50
DEFAULT_PURPOSE = (
    "Select the best supplied SWE-Lancer manager proposal using the authoritative "
    "task requirement, full proposal text, and inspected repository evidence."
)

_FORBIDDEN_AGENT_JUDGMENT_KEYS = frozenset(
    {
        "agent_choice",
        "agent_confidence",
        "initial_agent_choice",
        "my_choice",
        "preferred_answer",
        "preferred_option",
        "selected_option",
        "selected_proposal_id",
        "verdict",
    }
)
_ALLOWED_AGENT_STATE_KEYS = frozenset(
    {"repository_evidence", "verification", "agent_observations"}
)


def _forbidden_keys(value: object) -> list[str]:
    found: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key).lower().replace("-", "_").strip()
                if key in _FORBIDDEN_AGENT_JUDGMENT_KEYS:
                    found.add(key)
                walk(child)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for child in item:
                walk(child)

    walk(value)
    return sorted(found)


def parse_manager_proposals(raw: str) -> dict[str, str]:
    """Parse the public SWE-Lancer proposals field without consulting gold data."""
    if not isinstance(raw, str) or not raw.strip():
        raise WorkflowError("SWE-Lancer manager task has no proposal text")
    normalized_raw = raw.replace("\r\n", "\n")
    matches = list(
        re.finditer(r"(?m)^Proposal:\s*(\d+):\s*$", normalized_raw)
    )
    if len(matches) < 2 and "\\n" in normalized_raw:
        # The pinned SWE-Lancer CSV can surface embedded proposal line breaks as
        # escaped sequences after CSV decoding. Normalize that representation for
        # policy construction while retaining the exact resulting proposal text.
        normalized_raw = (
            normalized_raw.replace("\\r\\n", "\n").replace("\\n", "\n")
        )
        matches = list(
            re.finditer(r"(?m)^Proposal:\s*(\d+):\s*$", normalized_raw)
        )
    if len(matches) < 2:
        raise WorkflowError("SWE-Lancer manager task must contain at least two proposals")

    proposals: dict[str, str] = {}
    for index, match in enumerate(matches):
        proposal_id = f"proposal_{match.group(1)}"
        if proposal_id in proposals:
            raise WorkflowError(f"duplicate SWE-Lancer proposal ID {proposal_id}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_raw)
        body = normalized_raw[match.end() : end].strip()
        body = re.sub(r"\n-{10,}\s*$", "", body).strip()
        body = re.sub(r"\n---\s*$", "", body).strip()
        if not body:
            raise WorkflowError(f"SWE-Lancer proposal {proposal_id} is empty")
        proposals[proposal_id] = body
    return proposals


def load_manager_authoritative_context(
    csv_path: Path,
    *,
    sample_id: str,
) -> dict[str, object]:
    """Load only public task prompt fields; never inspect manager_data/gold."""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise WorkflowError(f"SWE-Lancer CSV not found: {csv_path}")

    selected: dict[str, str] | None = None
    with csv_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if str(row.get("question_id") or "") != sample_id:
                continue
            selected = {
                "question_id": str(row.get("question_id") or ""),
                "variant": str(row.get("variant") or ""),
                "title": str(row.get("title") or ""),
                "description": str(row.get("description") or ""),
                "proposals": str(row.get("proposals") or ""),
            }
            break

    if selected is None:
        raise WorkflowError(f"SWE-Lancer sample not found: {sample_id}")
    if selected["variant"] != "swe_manager":
        raise WorkflowError(
            f"SWE-Lancer sample {sample_id} is not a swe_manager task"
        )
    if not selected["title"].strip() or not selected["description"].strip():
        raise WorkflowError(
            f"SWE-Lancer sample {sample_id} is missing title/description"
        )

    proposals = parse_manager_proposals(selected["proposals"])
    return {
        "source": {
            "task": "inspect_evals/swe_lancer",
            "sample_id": sample_id,
            "csv_path": str(csv_path),
            "csv_sha256": sha256_file(csv_path),
        },
        "task": {
            "sample_id": sample_id,
            "title": selected["title"],
            "description": selected["description"],
            "proposals": proposals,
        },
    }


def _normalize_string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise WorkflowError(f"{label} must be a JSON array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise WorkflowError(f"{label}[{index}] must be a non-empty string")
        result.append(item)
    return result


def normalize_manager_agent_state(
    agent_state: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(agent_state, Mapping):
        raise WorkflowError("manager Jev agent state must be an object")
    unknown = sorted(set(map(str, agent_state)) - _ALLOWED_AGENT_STATE_KEYS)
    if unknown:
        raise WorkflowError(
            "manager Jev agent state contains unsupported fields: "
            + ", ".join(unknown)
        )
    forbidden = _forbidden_keys(agent_state)
    if forbidden:
        raise WorkflowError(
            "manager Jev neutral evidence contains agent judgment keys: "
            + ", ".join(forbidden)
        )

    evidence = agent_state.get("repository_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise WorkflowError(
            "manager Jev request requires at least one repository_evidence item"
        )
    normalized_evidence: list[dict[str, str]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            raise WorkflowError(
                f"repository_evidence[{index}] must be an object"
            )
        source = item.get("source")
        fact = item.get("fact", item.get("observation"))
        if not isinstance(source, str) or not source.strip():
            raise WorkflowError(
                f"repository_evidence[{index}].source must be non-empty"
            )
        if not isinstance(fact, str) or not fact.strip():
            raise WorkflowError(
                f"repository_evidence[{index}].fact must be non-empty"
            )
        normalized_evidence.append({"source": source, "fact": fact})

    verification = agent_state.get("verification")
    if not isinstance(verification, Mapping):
        raise WorkflowError(
            "manager Jev request requires explicit verification scope"
        )
    if set(map(str, verification)) != {"ran", "not_exercised"}:
        raise WorkflowError(
            "verification must contain exactly ran and not_exercised"
        )
    normalized_verification = {
        "ran": _normalize_string_list(
            verification.get("ran"),
            label="verification.ran",
        ),
        "not_exercised": _normalize_string_list(
            verification.get("not_exercised"),
            label="verification.not_exercised",
        ),
    }

    observations = agent_state.get("agent_observations")
    normalized_observations: list[dict[str, str]] = []
    if observations is not None:
        if not isinstance(observations, list):
            raise WorkflowError("agent_observations must be an array")
        for index, item in enumerate(observations):
            if not isinstance(item, Mapping):
                raise WorkflowError(
                    f"agent_observations[{index}] must be an object"
                )
            claim = item.get("claim")
            basis = item.get("basis")
            if not isinstance(claim, str) or not claim.strip():
                raise WorkflowError(
                    f"agent_observations[{index}].claim must be non-empty"
                )
            if not isinstance(basis, str) or not basis.strip():
                raise WorkflowError(
                    f"agent_observations[{index}].basis must be non-empty"
                )
            normalized_observations.append(
                {"claim": claim, "basis": basis}
            )

    result: dict[str, object] = {
        "repository_evidence": normalized_evidence,
        "verification": normalized_verification,
    }
    if normalized_observations:
        result["agent_observations"] = normalized_observations
    return result


def manager_questions(proposal_ids: Sequence[str]) -> dict[str, object]:
    proposal_ids = [str(item) for item in proposal_ids]
    if len(proposal_ids) < 2 or len(set(proposal_ids)) != len(proposal_ids):
        raise WorkflowError("manager policy requires at least two unique proposal IDs")
    criteria = {
        proposal_id: f"Official task proposal {proposal_id.removeprefix('proposal_')}"
        for proposal_id in proposal_ids
    }
    criteria["insufficient_evidence"] = (
        "The authoritative task material and inspected repository evidence do not "
        "justify selecting one proposal."
    )
    return {
        "best_proposal": {
            "type": "choice",
            "instructions": (
                "Which official proposal best satisfies the authoritative task "
                "requirement and supplied repository evidence? Select "
                "insufficient_evidence when the evidence does not justify a choice."
            ),
            "criteria": criteria,
        },
        "evidence_sufficient": {
            "type": "noul",
            "instructions": (
                "Is the supplied authoritative task material plus repository and "
                "verification evidence sufficient to make this proposal-selection "
                "decision without additional investigation?"
            ),
            "criteria": {
                "true": "Material evidence for the bounded choice is present.",
                "false": "Material evidence needed for the bounded choice is missing.",
            },
        },
    }


def inspect_manager_built_request(
    built: Mapping[str, object],
    *,
    authoritative: Mapping[str, object],
) -> dict[str, object]:
    request = built.get("request")
    if not isinstance(request, Mapping):
        return {"complete": False, "reason": "missing_request"}
    state = request.get("state")
    questions = request.get("questions")
    task = authoritative.get("task")
    if not isinstance(state, Mapping) or not isinstance(questions, Mapping):
        return {"complete": False, "reason": "missing_state_or_questions"}
    if not isinstance(task, Mapping):
        return {"complete": False, "reason": "missing_authoritative_task"}

    proposals = task.get("proposals")
    if not isinstance(proposals, Mapping):
        return {"complete": False, "reason": "missing_authoritative_proposals"}
    expected_ids = set(map(str, proposals))
    best = questions.get("best_proposal")
    criteria = best.get("criteria") if isinstance(best, Mapping) else None
    choice_ids = (
        set(map(str, criteria)) - {"insufficient_evidence"}
        if isinstance(criteria, Mapping)
        else set()
    )

    verification = state.get("verification")
    evidence = state.get("repository_evidence")
    checks = {
        "authoritative_task_exact": state.get("authoritative_task") == task,
        "all_proposals_present": (
            isinstance(state.get("authoritative_task"), Mapping)
            and state["authoritative_task"].get("proposals") == proposals
        ),
        "proposal_ids_match_choice": choice_ids == expected_ids,
        "insufficient_evidence_choice_present": (
            isinstance(criteria, Mapping)
            and "insufficient_evidence" in criteria
        ),
        "evidence_sufficiency_noul_present": (
            isinstance(questions.get("evidence_sufficient"), Mapping)
            and questions["evidence_sufficient"].get("type") == "noul"
        ),
        "repository_evidence_present": isinstance(evidence, list) and bool(evidence),
        "verification_scope_present": (
            isinstance(verification, Mapping)
            and set(map(str, verification)) == {"ran", "not_exercised"}
        ),
        "agent_judgment_keys_absent": not _forbidden_keys(state),
    }
    return {
        "complete": all(checks.values()),
        "checks": checks,
        "proposal_ids": sorted(expected_ids),
        "request_sha256": built.get("request_sha256"),
        "decision_sha256": built.get("decision_sha256"),
        "authoritative_task_sha256": sha256_json(task),
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
    }


def build_manager_jev_request(
    *,
    authoritative: Mapping[str, object],
    agent_state: Mapping[str, object],
    purpose: str = DEFAULT_PURPOSE,
    model: str | None = None,
    previous_decision_sha256: str | None = None,
    change_reason: str | None = None,
) -> dict[str, object]:
    task = authoritative.get("task")
    source = authoritative.get("source")
    if not isinstance(task, Mapping) or not isinstance(source, Mapping):
        raise WorkflowError("manager authoritative context is malformed")
    proposals = task.get("proposals")
    if not isinstance(proposals, Mapping):
        raise WorkflowError("manager authoritative context has no proposals")

    normalized_agent_state = normalize_manager_agent_state(agent_state)
    final_state: dict[str, object] = {
        "authoritative_task": dict(task),
        "repository_evidence": normalized_agent_state["repository_evidence"],
        "verification": normalized_agent_state["verification"],
    }
    if "agent_observations" in normalized_agent_state:
        final_state["agent_observations"] = normalized_agent_state["agent_observations"]

    questions = manager_questions(list(map(str, proposals)))
    built = build_jev_request(
        state=final_state,
        questions=questions,
        purpose=purpose or DEFAULT_PURPOSE,
        model=model,
        policy_id=POLICY_ID,
        previous_decision_sha256=previous_decision_sha256,
        change_reason=change_reason,
        agent_input={
            "state": dict(agent_state),
            "purpose": purpose,
            "previous_decision_sha256": previous_decision_sha256,
            "change_reason": change_reason,
        },
        transformation={
            "policy_version": POLICY_VERSION,
            "authoritative_source": dict(source),
            "authoritative_task_sha256": sha256_json(task),
            "proposal_ids": list(map(str, proposals)),
            "questions_constructed_by_policy": True,
        },
    )
    completeness = inspect_manager_built_request(
        built,
        authoritative=authoritative,
    )
    if completeness.get("complete") is not True:
        raise WorkflowError(
            "manager Jev request failed deterministic completeness policy"
        )
    built["completeness"] = completeness
    return built


def _history_record_for_decision(
    history_path: Path,
    decision_sha256: str,
) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{64}", decision_sha256) is None:
        raise WorkflowError("previous decision hash must be a lowercase SHA-256")
    target = Path(history_path)
    if not target.is_file():
        raise WorkflowError(
            "previous decision hash was supplied but no request history exists"
        )
    matches: list[dict[str, object]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError("manager Jev request history is malformed") from exc
        if (
            isinstance(item, dict)
            and item.get("status") == "success"
            and item.get("decision_sha256") == decision_sha256
            and item.get("policy_id") == POLICY_ID
        ):
            matches.append(item)
    if len(matches) != 1:
        raise WorkflowError(
            "previous decision hash must identify exactly one successful "
            "manager-policy request in the local history"
        )
    return matches[0]


def assess_manager_response(result: Mapping[str, object]) -> dict[str, object]:
    answers = result.get("answers")
    if not isinstance(answers, Mapping):
        raise WorkflowError("manager Jev response has no typed answers")
    best = answers.get("best_proposal")
    sufficient = answers.get("evidence_sufficient")
    if not isinstance(best, Mapping) or not isinstance(sufficient, Mapping):
        raise WorkflowError("manager Jev response is missing required batch answers")

    choice = best.get("choice")
    probability = sufficient.get("probability")
    explicit_insufficiency = choice == "insufficient_evidence"
    noul_insufficiency = (
        isinstance(probability, (int, float))
        and not isinstance(probability, bool)
        and float(probability) < EVIDENCE_SUFFICIENCY_REBUILD_THRESHOLD
    )
    rebuild_permitted = explicit_insufficiency or noul_insufficiency
    reasons: list[str] = []
    if explicit_insufficiency:
        reasons.append("choice_insufficient_evidence")
    if noul_insufficiency:
        reasons.append("evidence_sufficiency_below_policy_threshold")
    return {
        "best_proposal": choice,
        "evidence_sufficient_probability": probability,
        "evidence_sufficiency_rebuild_threshold": EVIDENCE_SUFFICIENCY_REBUILD_THRESHOLD,
        "explicit_insufficiency": explicit_insufficiency,
        "noul_insufficiency": noul_insufficiency,
        "rebuild_permitted": rebuild_permitted,
        "rebuild_reasons": reasons,
        "rebuild_rule": (
            "A second semantic request requires materially new evidence or changed "
            "alternatives and must cite the prior decision_sha256. The current "
            "manager policy recommends rebuilding when Choice explicitly returns "
            "insufficient_evidence or the evidence-sufficiency Noul falls below "
            "the frozen policy threshold. Low Choice/Score confidence alone is not "
            "a rebuild trigger."
        ),
    }


def manager_jev_bridged_tool_v2(
    *,
    authoritative: Mapping[str, object],
    receipt_path: Path,
    history_path: Path,
    model: str | None,
    study_id: str,
) -> Any:
    """Expose a policy-specific host tool while keeping credentials off-agent."""
    try:
        from inspect_ai.tool import tool
    except ImportError as exc:
        raise WorkflowError(
            "Inspect AI is required to expose the manager Jev v2 bridged tool"
        ) from exc

    @tool
    def jev_manager_decision():
        async def execute(
            repository_evidence: list[dict[str, str]],
            verification: dict[str, list[str]],
            agent_observations: list[dict[str, str]] | None = None,
            purpose: str = "",
            previous_decision_sha256: str = "",
            change_reason: str = "",
        ) -> str:
            """Build and execute one complete SWE-manager Jev decision request.

            The host injects the exact authoritative task requirement and every
            official proposal from the frozen SWE-Lancer source. Supply only
            repository evidence you inspected and explicit verification scope.

            Args:
                repository_evidence: One or more {"source": "...", "fact": "..."}
                    evidence records grounded in repository inspection.
                verification: Exactly {"ran": [...], "not_exercised": [...]}.
                    Use empty arrays when appropriate; never imply a check ran when
                    it did not.
                agent_observations: Optional explicitly labeled observations with
                    {"claim": "...", "basis": "..."}; keep opinions/verdicts out.
                purpose: Optional short description of why this decision matters.
                previous_decision_sha256: Prior decision hash only for a changed
                    revision after materially new evidence or changed alternatives.
                change_reason: Required with previous_decision_sha256; state what
                    materially changed. An unchanged revision is rejected.
            """
            prior_hash = previous_decision_sha256.strip() or None
            prior_record: dict[str, object] | None = None
            if prior_hash is not None:
                prior_record = _history_record_for_decision(
                    history_path,
                    prior_hash,
                )

            agent_state: dict[str, object] = {
                "repository_evidence": repository_evidence,
                "verification": verification,
            }
            if agent_observations:
                agent_state["agent_observations"] = agent_observations
            built = build_manager_jev_request(
                authoritative=authoritative,
                agent_state=agent_state,
                purpose=purpose or DEFAULT_PURPOSE,
                model=model,
                previous_decision_sha256=prior_hash,
                change_reason=change_reason.strip() or None,
            )
            result = await asyncio.to_thread(
                execute_built_jev_request,
                built,
                receipt_path=receipt_path,
                history_path=history_path,
                study_id=study_id,
            )
            assessment = assess_manager_response(result)
            return json.dumps(
                {
                    **result,
                    "context_complete": True,
                    "policy_id": POLICY_ID,
                    "policy_version": POLICY_VERSION,
                    "supersedes_verified_history": prior_record is not None,
                    "assessment": assessment,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

        return execute

    return jev_manager_decision()
