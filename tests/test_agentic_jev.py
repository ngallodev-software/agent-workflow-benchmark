from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev import (
    PILOT_AGENT_MODEL,
    PILOT_AGENT_REASONING_EFFORT,
    PILOT_CODEX_MODEL_CONFIG,
    PILOT_CODEX_MIN_VERSION,
    PILOT_ARMS,
    agentic_jev_skill_path,
    agentic_jev_skill_sha256,
    build_agentic_jev_solver,
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
    assert path.name == "SKILL.md"
    assert path.parent.is_dir()
    assert (path.parent / "SKILL.md") == path
    assert "Jev" in path.read_text(encoding="utf-8")
    assert len(agentic_jev_skill_sha256()) == 64

    assert [(a.arm_id, a.typesafe_skill, a.jev_tool) for a in PILOT_ARMS] == [
        ("A-baseline", False, False),
        ("B-skill-only", True, False),
        ("C-skill-plus-jev", True, True),
    ]
    manifest = pilot_treatment_manifest()
    assert manifest["agent"] == {
        "model": "openai-api/codex-lb/gpt-6-luna",
        "reasoning_effort": "high",
        "responses_api": True,
        "codex_model_config": "gpt-6-luna",
        "codex_min_version": "0.155.0",
    }
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
    monkeypatch.setattr(agentic_jev_module, "_inspect_harness_sha256", lambda: "a" * 64)
    monkeypatch.setattr(
        agentic_jev_module,
        "_sandbox_image_identity",
        lambda: {
            "reference": "python:3.12-bookworm",
            "image_id": "sha256:image-a",
            "repo_digests": ["python@sha256:image-a"],
        },
    )
    monkeypatch.setattr(inspect_adjudication, "_require_inspect_dependencies", lambda: (object(), object()))
    monkeypatch.setattr(inspect_adjudication, "_sandbox_platform", lambda: "linux-x64")
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
        agent_model=PILOT_AGENT_MODEL,
        agent_reasoning_effort=PILOT_AGENT_REASONING_EFFORT,
        agent_model_args={"responses_api": True},
        jev_model=None,
    )

    assert result["codex_cli"]["resolved"] == "9.9.9"
    assert result["codex_model_config"] == "gpt-6-luna"
    assert result["agent_model"] == "openai-api/codex-lb/gpt-6-luna"
    assert result["agent_reasoning_effort"] == "high"
    assert result["agent_model_args"] == {"responses_api": True}
    assert result["skill"]["sha256"] == agentic_jev_skill_sha256()
    assert result["tasks"]["count"] == 24
    assert result["host_tool"]["typesafe_sdk_version"] == "0.6.0"
    assert len(result["host_tool"]["implementation_sha256"]) == 64
    assert result["inspect_harness"]["implementation_sha256"] == "a" * 64
    assert result["sandbox_image"]["image_id"] == "sha256:image-a"
    loaded = load_agentic_jev_runtime_lock(lock_path)
    assert loaded["tasks"]["sha256"] == result["tasks"]["sha256"]

    monkeypatch.setattr(
        inspect_adjudication,
        "_docker_identity",
        lambda: {"docker": "Docker drift", "compose": "Compose test"},
    )
    with pytest.raises(WorkflowError, match="Docker/Compose identity"):
        load_agentic_jev_runtime_lock(lock_path)

    monkeypatch.setattr(
        inspect_adjudication,
        "_docker_identity",
        lambda: {"docker": "Docker test", "compose": "Compose test"},
    )
    monkeypatch.setattr(
        agentic_jev_module,
        "_sandbox_image_identity",
        lambda: {
            "reference": "python:3.12-bookworm",
            "image_id": "sha256:image-b",
            "repo_digests": ["python@sha256:image-b"],
        },
    )
    with pytest.raises(WorkflowError, match="sandbox image identity"):
        load_agentic_jev_runtime_lock(lock_path)

    monkeypatch.setattr(
        agentic_jev_module,
        "_sandbox_image_identity",
        lambda: {
            "reference": "python:3.12-bookworm",
            "image_id": "sha256:image-a",
            "repo_digests": ["python@sha256:image-a"],
        },
    )
    monkeypatch.setattr(agentic_jev_module, "_inspect_harness_sha256", lambda: "b" * 64)
    with pytest.raises(WorkflowError, match="Inspect harness implementation"):
        load_agentic_jev_runtime_lock(lock_path)

    monkeypatch.setattr(agentic_jev_module, "_inspect_harness_sha256", lambda: "a" * 64)
    monkeypatch.setattr(agentic_jev_module, "_typesafe_sdk_version", lambda: "0.6.1")
    with pytest.raises(WorkflowError, match="TypeSafe SDK version"):
        load_agentic_jev_runtime_lock(lock_path)


def test_agentic_jev_runtime_lock_rejects_model_or_reasoning_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from agent_workflow_benchmark.benchmarking import agentic_jev as agentic_jev_module
    from agent_workflow_benchmark.benchmarking import inspect_adjudication

    monkeypatch.setattr(agentic_jev_module, "_typesafe_sdk_version", lambda: "0.6.0")
    monkeypatch.setattr(agentic_jev_module, "_inspect_harness_sha256", lambda: "a" * 64)
    monkeypatch.setattr(
        agentic_jev_module,
        "_sandbox_image_identity",
        lambda: {
            "reference": "python:3.12-bookworm",
            "image_id": "sha256:image-a",
            "repo_digests": ["python@sha256:image-a"],
        },
    )
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

    with pytest.raises(WorkflowError, match="model is frozen"):
        create_agentic_jev_runtime_lock(
            destination=tmp_path / "wrong-model.json",
            tasks_path=tasks,
            agent_model="openai-api/codex-lb/deepseek-flash",
            agent_reasoning_effort="high",
            agent_model_args={"responses_api": True},
        )

    with pytest.raises(WorkflowError, match="reasoning effort is frozen"):
        create_agentic_jev_runtime_lock(
            destination=tmp_path / "wrong-effort.json",
            tasks_path=tasks,
            agent_model=PILOT_AGENT_MODEL,
            agent_reasoning_effort="medium",
            agent_model_args={"responses_api": True},
        )

    with pytest.raises(WorkflowError, match="generation config"):
        create_agentic_jev_runtime_lock(
            destination=tmp_path / "reasoning-in-model-args.json",
            tasks_path=tasks,
            agent_model=PILOT_AGENT_MODEL,
            agent_reasoning_effort=PILOT_AGENT_REASONING_EFFORT,
            agent_model_args={
                "responses_api": True,
                "reasoning_effort": "high",
            },
        )


def test_agentic_jev_runtime_lock_rejects_codex_too_old_for_luna(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from agent_workflow_benchmark.benchmarking import agentic_jev as agentic_jev_module
    from agent_workflow_benchmark.benchmarking import inspect_adjudication

    monkeypatch.setattr(agentic_jev_module, "_typesafe_sdk_version", lambda: "0.6.0")
    monkeypatch.setattr(agentic_jev_module, "_inspect_harness_sha256", lambda: "a" * 64)
    monkeypatch.setattr(
        agentic_jev_module,
        "_sandbox_image_identity",
        lambda: {
            "reference": "python:3.12-bookworm",
            "image_id": "sha256:image-a",
            "repo_digests": ["python@sha256:image-a"],
        },
    )
    monkeypatch.setattr(
        inspect_adjudication,
        "_docker_identity",
        lambda: {"docker": "Docker test", "compose": "Compose test"},
    )
    monkeypatch.setattr(
        inspect_adjudication,
        "resolve_latest_codex_cli",
        lambda: {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.154.9",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex",
        },
    )
    tasks = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_workflow_benchmark"
        / "assets"
        / "agentic-jev-pilot"
        / "tasks-v0.1.0-dev.1.json"
    )

    with pytest.raises(WorkflowError, match="Codex CLI >=0.155.0"):
        create_agentic_jev_runtime_lock(
            destination=tmp_path / "old-codex.json",
            tasks_path=tasks,
            agent_model=PILOT_AGENT_MODEL,
            agent_reasoning_effort=PILOT_AGENT_REASONING_EFFORT,
            agent_model_args={"responses_api": True},
        )


def test_agentic_solver_passes_skill_directory_to_inspect(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeBridgedToolsSpec:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_codex_cli(**kwargs):
        captured.update(kwargs)
        return object()

    inspect_ai_agent = types.ModuleType("inspect_ai.agent")
    inspect_ai_agent.BridgedToolsSpec = FakeBridgedToolsSpec
    inspect_swe = types.ModuleType("inspect_swe")
    inspect_swe.codex_cli = fake_codex_cli
    monkeypatch.setitem(sys.modules, "inspect_ai.agent", inspect_ai_agent)
    monkeypatch.setitem(sys.modules, "inspect_swe", inspect_swe)

    solver = build_agentic_jev_solver(
        arm_id="B-skill-only",
        codex_version="0.159.1",
        receipt_path=tmp_path / "receipts.jsonl",
    )

    assert solver is not None
    assert captured["skills"] == [agentic_jev_skill_path().parent]
    assert captured["skills"][0].is_dir()
    assert (captured["skills"][0] / "SKILL.md").is_file()
