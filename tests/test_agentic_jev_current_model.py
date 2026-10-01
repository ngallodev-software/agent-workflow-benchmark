from __future__ import annotations

import json

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev_current_model import (
    QUALIFICATION_FILES,
    QUALIFICATION_PROMPT,
    SUPPORTED_MODELS,
    inspect_jev_receipt_context,
    parse_decision_record,
)


def _complete_receipt() -> dict[str, object]:
    return {
        "purpose": "Choose between two cache invalidation proposals after repository inspection.",
        "state_sha256": "a" * 64,
        "questions_sha256": "b" * 64,
        "request_sha256": "c" * 64,
        "request": {
            "state": {
                "requirement": QUALIFICATION_FILES["requirement.md"],
                "candidates": {
                    "proposal_1": QUALIFICATION_FILES["proposal_1.md"],
                    "proposal_2": QUALIFICATION_FILES["proposal_2.md"],
                },
                "unchanged_code": QUALIFICATION_FILES["src/cache.py"],
                "verification": QUALIFICATION_FILES["verification.txt"],
            },
            "questions": {
                "best_proposal": {
                    "type": "choice",
                    "instructions": "Which proposal best fits the requirement and evidence?",
                    "criteria": {"proposal_1": "local", "proposal_2": "centralized"},
                }
            },
        },
    }


def test_current_model_qualification_supports_luna_and_sol() -> None:
    assert SUPPORTED_MODELS == {
        "openai-api/codex-lb/gpt-6-luna": "gpt-6-luna",
        "openai-api/codex-lb/gpt-6.1-sol": "gpt-6.1-sol",
    }


def test_qualification_prompt_does_not_name_jev_or_typesafe() -> None:
    prompt = QUALIFICATION_PROMPT.lower()
    assert "jev" not in prompt
    assert "typesafe" not in prompt
    assert "private chain-of-thought" in prompt


def test_context_inspection_requires_fixture_complete_primary_evidence() -> None:
    result = inspect_jev_receipt_context(_complete_receipt())
    assert all(result["anchors"].values())
    assert result["checks"] == {
        "all_primary_evidence_present": True,
        "choice_question_present": True,
        "purpose_present": True,
        "agent_judgment_keys_absent": True,
    }
    assert result["choice_question_ids"] == ["best_proposal"]


def test_context_inspection_detects_missing_dependency_evidence() -> None:
    receipt = _complete_receipt()
    del receipt["request"]["state"]["unchanged_code"]
    result = inspect_jev_receipt_context(receipt)
    assert result["anchors"]["unchanged_dependency"] is False
    assert result["checks"]["all_primary_evidence_present"] is False


def test_context_inspection_rejects_agent_verdict_in_primary_state() -> None:
    receipt = _complete_receipt()
    receipt["request"]["state"]["preferred_option"] = "proposal_2"
    result = inspect_jev_receipt_context(receipt)
    assert result["checks"]["agent_judgment_keys_absent"] is False
    assert result["forbidden_agent_judgment_keys"] == ["preferred_option"]


def test_parse_decision_record_requires_observable_justification() -> None:
    value = {
        "selected_option": "proposal_2",
        "justification": (
            "Both candidates pass the supplied verification, so the deciding evidence is the "
            "shared CacheStore boundary: centralizing invalidation keeps one invariant while "
            "the call-site design duplicates coordination logic."
        ),
        "evidence_refs": ["requirement.md", "proposal_2.md", "src/cache.py", "verification.txt"],
        "tradeoff": "Broader shared-path review surface versus one centralized invalidation invariant.",
        "semantic_evidence_reconciliation": (
            "The semantic evidence was treated as advisory and was consistent with the primary "
            "repository evidence; deterministic checks remained authoritative."
        ),
        "remaining_uncertainty": "Multi-process behavior was not exercised, but it is outside the current single-process requirement.",
    }
    assert parse_decision_record(json.dumps(value)) == value


def test_parse_decision_record_rejects_non_json_or_thin_rationale() -> None:
    with pytest.raises(WorkflowError, match="not exactly one JSON object"):
        parse_decision_record("proposal_2 because it is cleaner")

    value = {
        "selected_option": "proposal_2",
        "justification": "too short",
        "evidence_refs": ["requirement.md", "proposal_2.md", "src/cache.py"],
        "tradeoff": "Centralized invariant versus review surface.",
        "semantic_evidence_reconciliation": "Semantic evidence agreed with inspected evidence.",
        "remaining_uncertainty": None,
    }
    with pytest.raises(WorkflowError, match="80-1200"):
        parse_decision_record(json.dumps(value))


def test_parse_decision_record_rejects_unknown_or_duplicate_evidence_refs() -> None:
    base = {
        "selected_option": "proposal_1",
        "justification": "The local design preserves the same verified behavior while minimizing shared-path change; the principal cost is duplicated coordination that future changes must keep consistent.",
        "tradeoff": "Small reversible diff versus duplicated invalidation coordination across call sites.",
        "semantic_evidence_reconciliation": "Semantic evidence was advisory and reconciled against the supplied tests and requirement.",
        "remaining_uncertainty": None,
    }
    with pytest.raises(WorkflowError, match="unknown evidence refs"):
        parse_decision_record(json.dumps({**base, "evidence_refs": ["requirement.md", "proposal_1.md", "missing.txt"]}))
    with pytest.raises(WorkflowError, match="must be unique"):
        parse_decision_record(json.dumps({**base, "evidence_refs": ["requirement.md", "proposal_1.md", "proposal_1.md"]}))
