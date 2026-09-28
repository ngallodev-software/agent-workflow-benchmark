from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev import (
    PILOT_ARMS,
    agentic_jev_skill_path,
    agentic_jev_skill_sha256,
    create_agentic_jev_runtime_lock,
    execute_jev_request,
    load_agentic_jev_runtime_lock,
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


def test_agentic_jev_runtime_lock_binds_model_skill_and_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from agent_workflow_benchmark.benchmarking import agentic_jev as agentic_jev_module
    from agent_workflow_benchmark.benchmarking import inspect_adjudication

    monkeypatch.setattr(agentic_jev_module, "_typesafe_sdk_version", lambda: "0.6.0")
    monkeypatch.setattr(
        inspect_adjudication,
        "resolve_latest_codex_cli",
        lambda: {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "9.9.9",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex",
        },
    )
    monkeypatch.setattr(
        inspect_adjudication,
        "_docker_identity",
        lambda: {"docker": "Docker test", "compose": "Compose test"},
    )
    tasks = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_workflow_benchmark"
        / "assets"
        / "agentic-jev-pilot"
        / "tasks-v0.1.0-dev.1.json"
    )
    lock_path = tmp_path / "runtime-lock.json"
    result = create_agentic_jev_runtime_lock(
        destination=lock_path,
        tasks_path=tasks,
        agent_model="openai-api/codex-lb/test-model",
        agent_model_args={"responses_api": True},
        jev_model=None,
    )

    assert result["codex_cli"]["resolved"] == "9.9.9"
    assert result["agent_model"] == "openai-api/codex-lb/test-model"
    assert result["agent_model_args"] == {"responses_api": True}
    assert result["skill"]["sha256"] == agentic_jev_skill_sha256()
    assert result["tasks"]["count"] == 24
    assert result["host_tool"]["typesafe_sdk_version"] == "0.6.0"
    assert len(result["host_tool"]["implementation_sha256"]) == 64
    loaded = load_agentic_jev_runtime_lock(lock_path)
    assert loaded["tasks"]["sha256"] == result["tasks"]["sha256"]

    monkeypatch.setattr(agentic_jev_module, "_typesafe_sdk_version", lambda: "0.6.1")
    with pytest.raises(WorkflowError, match="TypeSafe SDK version"):
        load_agentic_jev_runtime_lock(lock_path)
