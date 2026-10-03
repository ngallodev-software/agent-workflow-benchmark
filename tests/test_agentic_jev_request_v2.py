from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import (
    build_jev_request,
    execute_built_jev_request,
    verify_built_jev_request,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2 import (
    EVIDENCE_SUFFICIENCY_REBUILD_THRESHOLD,
    POLICY_ID,
    assess_manager_response,
    build_manager_jev_request,
    inspect_manager_built_request,
    load_manager_authoritative_context,
)


class _Choice:
    choice = "proposal_1"
    confidence = 0.76
    probabilities = {
        "proposal_0": 0.05,
        "proposal_1": 0.76,
        "proposal_2": 0.17,
        "insufficient_evidence": 0.02,
    }


class _Noul:
    noul = 0.82
    probabilities = {"false": 0.18, "true": 0.82}


class _Usage:
    def model_dump(self):
        return {
            "input_tokens": 200,
            "output_tokens": 30,
            "total_tokens": 230,
        }


class _Client:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions, model=None):
        self.calls.append((state, questions, model))
        return SimpleNamespace(
            answers={
                "best_proposal": _Choice(),
                "evidence_sufficient": _Noul(),
            },
            request_id="req-v2",
            model="jev-test",
            usage=_Usage(),
        )


def _manager_csv(path: Path) -> Path:
    fields = [
        "question_id",
        "variant",
        "price",
        "price_limit",
        "manager_data",
        "manager_commit",
        "acceptable_folders",
        "cwd",
        "set",
        "title",
        "description",
        "proposals",
    ]
    row = {
        "question_id": "observed-manager-0",
        "variant": "swe_manager",
        "price": "1000",
        "price_limit": "2000000",
        # Deliberately place forbidden/gold-looking material here. The loader must
        # never project manager_data into authoritative context.
        "manager_data": '{"correct_proposal":{"id":1}}',
        "manager_commit": "deadbeef",
        "acceptable_folders": "[]",
        "cwd": "/app/expensify",
        "set": "diamond",
        "title": "Whitespace is accepted as a task description",
        "description": "Expected: task description whitespace should be trimmed.",
        "proposals": (
            "Proposal: 0:\nDo nothing because input should remain untouched.\n"
            "--------------------------------------------\n\n"
            "Proposal: 1:\nTrim title and description in the relevant task screens.\n"
            "--------------------------------------------\n\n"
            "Proposal: 2:\nTrim at the shared task state boundary.\n"
            "--------------------------------------------\n\n---"
        ),
    }
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    return path


def _agent_state() -> dict[str, object]:
    return {
        "repository_evidence": [
            {
                "source": "src/pages/tasks/NewTaskDetailsPage.js:37-52",
                "fact": "The submit path stores the task description unchanged.",
            },
            {
                "source": "src/libs/actions/Task.js:154-179",
                "fact": "The task action persists description values unchanged.",
            },
        ],
        "verification": {
            "ran": ["Inspected the cited source paths."],
            "not_exercised": ["No runtime test was executed."],
        },
    }


def test_generic_builder_is_deterministic_redacts_secrets_and_rejects_unchanged_revision():
    questions = {
        "best": {
            "type": "choice",
            "instructions": "Which option best fits?",
            "criteria": {
                "a": "Option A",
                "b": "Option B",
                "insufficient_evidence": "Need more evidence",
            },
        },
        "supported": {
            "type": "noul",
            "instructions": "Is the supplied evidence sufficient?",
            "criteria": {
                "true": "Enough evidence",
                "false": "Missing evidence",
            },
        },
    }
    first = build_jev_request(
        state={
            "requirement": "Preserve behavior.",
            "api_key": "secret-value",
            "evidence": ["source:a"],
        },
        questions=questions,
        purpose="Bounded test decision.",
        model="jev-test",
    )
    same = build_jev_request(
        state={
            "requirement": "Preserve behavior.",
            "api_key": "another-secret",
            "evidence": ["source:a"],
        },
        questions=questions,
        purpose="Bounded test decision.",
        model="jev-test",
    )
    # Secret-like content is projected to the same deterministic redacted value.
    assert first["request_sha256"] == same["request_sha256"]
    assert first["request"]["state"]["api_key"] == "[redacted]"
    assert first["privacy"]["redacted_paths"] == ["$.state.api_key"]

    with pytest.raises(WorkflowError, match="semantically unchanged"):
        build_jev_request(
            state={
                "requirement": "Preserve behavior.",
                "api_key": "new-secret",
                "evidence": ["source:a"],
            },
            questions=questions,
            purpose="Changed prose does not matter.",
            model="jev-test",
            previous_decision_sha256=first["decision_sha256"],
            change_reason="No actual evidence change.",
        )

    revised = build_jev_request(
        state={
            "requirement": "Preserve behavior.",
            "api_key": "new-secret",
            "evidence": ["source:a", "source:b"],
        },
        questions=questions,
        purpose="Bounded test decision.",
        model="jev-test",
        previous_decision_sha256=first["decision_sha256"],
        change_reason="Added source:b after follow-up inspection.",
    )
    assert revised["decision_sha256"] != first["decision_sha256"]
    assert revised["revision"]["previous_decision_sha256"] == first["decision_sha256"]


def test_builder_rejects_silent_truncation_conditions():
    questions = {
        "supported": {
            "type": "noul",
            "instructions": "Is this enough evidence?",
        }
    }
    with pytest.raises(WorkflowError, match="8000 characters"):
        build_jev_request(
            state={"evidence": "x" * 8001},
            questions=questions,
            purpose="test",
        )
    with pytest.raises(WorkflowError, match="non-empty object"):
        build_jev_request(
            state={},
            questions=questions,
            purpose="test",
        )


def test_execute_built_request_logs_exact_provider_dispatch_and_detects_mutation(
    tmp_path: Path,
):
    csv_path = _manager_csv(tmp_path / "tasks.csv")
    authoritative = load_manager_authoritative_context(
        csv_path,
        sample_id="observed-manager-0",
    )
    built = build_manager_jev_request(
        authoritative=authoritative,
        agent_state=_agent_state(),
        model="jev-test",
    )
    client = _Client()
    receipt_path = tmp_path / "receipt.jsonl"
    history_path = tmp_path / "history.jsonl"
    result = execute_built_jev_request(
        built,
        receipt_path=receipt_path,
        history_path=history_path,
        study_id="test-study",
        client=client,
    )
    assert result["status"] == "success"
    assert len(client.calls) == 1

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))
    dispatched_state, dispatched_questions, dispatched_model = client.calls[0]
    assert history["request"] == {
        "state": dispatched_state,
        "questions": dispatched_questions,
        "model": dispatched_model,
    }
    assert receipt["request"] == {
        "state": dispatched_state,
        "questions": dispatched_questions,
    }
    assert receipt["requested_model"] == dispatched_model
    assert history["request_sha256"] == built["request_sha256"]
    assert receipt["request_sha256"] == built["request_sha256"]
    assert history["agent_input_sha256"] == built["agent_input_sha256"]

    tampered = json.loads(json.dumps(built))
    tampered["request"]["state"]["repository_evidence"][0]["fact"] = "tampered"
    with pytest.raises(WorkflowError, match="changed after validation"):
        verify_built_jev_request(tampered)


def test_manager_policy_injects_exact_authoritative_context_and_never_loads_gold(
    tmp_path: Path,
):
    csv_path = _manager_csv(tmp_path / "tasks.csv")
    authoritative = load_manager_authoritative_context(
        csv_path,
        sample_id="observed-manager-0",
    )
    serialized = json.dumps(authoritative)
    assert "correct_proposal" not in serialized
    assert "deadbeef" not in serialized
    task = authoritative["task"]
    assert task["title"] == "Whitespace is accepted as a task description"
    assert set(task["proposals"]) == {"proposal_0", "proposal_1", "proposal_2"}

    built = build_manager_jev_request(
        authoritative=authoritative,
        agent_state=_agent_state(),
    )
    state = built["request"]["state"]
    assert state["authoritative_task"] == task
    assert state["authoritative_task"]["proposals"] == task["proposals"]
    checks = inspect_manager_built_request(
        built,
        authoritative=authoritative,
    )
    assert checks["complete"] is True
    assert all(checks["checks"].values())
    criteria = built["request"]["questions"]["best_proposal"]["criteria"]
    assert set(criteria) == {
        "proposal_0",
        "proposal_1",
        "proposal_2",
        "insufficient_evidence",
    }


def test_manager_policy_rejects_agent_verdicts_and_missing_verification(tmp_path: Path):
    authoritative = load_manager_authoritative_context(
        _manager_csv(tmp_path / "tasks.csv"),
        sample_id="observed-manager-0",
    )
    bad = _agent_state()
    bad["selected_proposal_id"] = "proposal_1"
    with pytest.raises(WorkflowError, match="unsupported fields"):
        build_manager_jev_request(
            authoritative=authoritative,
            agent_state=bad,
        )

    missing = _agent_state()
    del missing["verification"]
    with pytest.raises(WorkflowError, match="verification scope"):
        build_manager_jev_request(
            authoritative=authoritative,
            agent_state=missing,
        )


def test_manager_response_rebuild_signal_uses_explicit_insufficiency_or_frozen_noul_threshold():
    enough = assess_manager_response(
        {
            "answers": {
                "best_proposal": {
                    "choice": "proposal_1",
                },
                "evidence_sufficient": {
                    "probability": 0.8,
                },
            }
        }
    )
    assert enough["rebuild_permitted"] is False

    no_match = assess_manager_response(
        {
            "answers": {
                "best_proposal": {
                    "choice": "insufficient_evidence",
                },
                "evidence_sufficient": {
                    "probability": 0.8,
                },
            }
        }
    )
    assert no_match["rebuild_permitted"] is True
    assert "choice_insufficient_evidence" in no_match["rebuild_reasons"]

    low_noul = assess_manager_response(
        {
            "answers": {
                "best_proposal": {
                    "choice": "proposal_1",
                },
                "evidence_sufficient": {
                    "probability": EVIDENCE_SUFFICIENCY_REBUILD_THRESHOLD - 0.01,
                },
            }
        }
    )
    assert low_noul["rebuild_permitted"] is True
    assert "evidence_sufficiency_below_policy_threshold" in low_noul["rebuild_reasons"]
