from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev import (
    PILOT_ARMS,
    agentic_jev_skill_path,
    agentic_jev_skill_sha256,
    execute_jev_request,
    load_pilot_tasks,
    pilot_treatment_manifest,
)


class _ChoiceAnswer:
    choice = "review"
    confidence = 0.91
    probabilities = {
        "implementation": 0.03,
        "diagnosis": 0.03,
        "review": 0.90,
        "documentation": 0.02,
        "other": 0.02,
    }


class _NoulAnswer:
    noul = 0.23
    probabilities = {"false": 0.77, "true": 0.23}


class _ScoreAnswer:
    score = 1.2
    confidence = 0.72
    probabilities = {"0": 0.1, "1": 0.6, "2": 0.3}


class _Usage:
    def model_dump(self):
        return {
            "input_tokens": 120,
            "output_tokens": 12,
            "total_tokens": 132,
        }


class _Response:
    request_id = "req-pilot"
    model = "jev-test"
    usage = _Usage()

    def __init__(self):
        self.answers = {
            "kind": _ChoiceAnswer(),
            "need_user": _NoulAnswer(),
            "risk": _ScoreAnswer(),
        }


class _Client:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions, model=None):
        self.calls.append((state, questions, model))
        assert state["api_key"] == "[redacted]"
        assert state["nested"]["access_token"] == "[redacted]"
        assert set(questions) == {"kind", "need_user", "risk"}
        return _Response()


def test_execute_jev_request_is_typed_redacted_and_receipted(tmp_path: Path):
    receipt = tmp_path / "calls.jsonl"
    client = _Client()
    result = execute_jev_request(
        state={
            "task": "Review the parser change.",
            "api_key": "super-secret",
            "nested": {"access_token": "also-secret"},
        },
        questions={
            "kind": {
                "type": "choice",
                "instructions": "Choose the primary work type.",
                "criteria": {
                    "implementation": "change code",
                    "diagnosis": "investigate",
                    "review": "assess",
                    "documentation": "write docs",
                    "other": "none",
                },
            },
            "need_user": {
                "type": "noul",
                "instructions": "Is a material user decision missing?",
            },
            "risk": {
                "type": "score",
                "instructions": "Score consequence of a wrong interpretation.",
                "criteria": ["low", "moderate", "high"],
            },
        },
        purpose="pilot-test",
        model="jev-test",
        client=client,
        receipt_path=receipt,
    )

    assert result["status"] == "success"
    assert result["request_id"] == "req-pilot"
    assert result["model"] == "jev-test"
    assert result["answers"]["kind"]["choice"] == "review"
    assert result["answers"]["need_user"]["probability"] == pytest.approx(0.23)
    assert result["answers"]["risk"]["score"] == pytest.approx(1.2)
    assert result["usage"]["provider_total_tokens"] == 132

    raw = receipt.read_text(encoding="utf-8")
    assert "super-secret" not in raw
    assert "also-secret" not in raw
    record = json.loads(raw)
    assert record["status"] == "success"
    assert record["privacy"]["credentials_in_sandbox"] is False
    assert record["primitive_counts"] == {"choice": 1, "noul": 1, "score": 1}
    assert record["request"]["state"]["api_key"] == "[redacted]"


def test_execute_jev_request_rejects_unbounded_question_contract():
    with pytest.raises(WorkflowError, match="unsupported type"):
        execute_jev_request(
            state={"task": "x"},
            questions={
                "bad": {
                    "type": "free_text",
                    "instructions": "Explain everything.",
                }
            },
            client=_Client(),
        )


def test_frozen_skill_and_three_arm_treatment_manifest():
    path = agentic_jev_skill_path()
    assert path.is_file()
    assert "Jev" in path.read_text(encoding="utf-8")
    assert len(agentic_jev_skill_sha256()) == 64

    assert [(a.arm_id, a.typesafe_skill, a.jev_tool) for a in PILOT_ARMS] == [
        ("A-baseline", False, False),
        ("B-skill-only", True, False),
        ("C-skill-plus-jev", True, True),
    ]
    manifest = pilot_treatment_manifest()
    assert manifest["skill"]["upstream_commit"] == (
        "65a39f393687675ce170e6094757de20370365b9"
    )
    assert manifest["tool"]["execution_location"] == "host"
    assert manifest["tool"]["api_key_location"] == "host-only"


def test_packaged_agentic_jev_pilot_has_exactly_24_hidden_tagged_tasks():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_workflow_benchmark"
        / "assets"
        / "agentic-jev-pilot"
        / "tasks-v0.1.0-dev.1.json"
    )
    value = load_pilot_tasks(path)
    assert value["development_only"] is True
    assert len(value["tasks"]) == 24
    assert len({task["task_id"] for task in value["tasks"]}) == 24
    assert all(task["authoring_tags"] for task in value["tasks"])
    assert all(task["files"] for task in value["tasks"])
