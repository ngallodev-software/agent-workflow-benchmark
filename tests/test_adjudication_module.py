from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.adjudication_module import (
    ABC_ADJUDICATION_MODULE_SCHEMA,
    validate_abc_adjudication_module,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "abc-adjudication" / "routing-semantic-v1.module.json"


def _copy_module(tmp_path: Path, mutate=None) -> Path:
    value = json.loads(MODULE.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(value)
    path = tmp_path / "module.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_routing_semantic_abc_module_validates():
    result = validate_abc_adjudication_module(MODULE)
    assert result["valid"] is True
    assert result["schema"] == ABC_ADJUDICATION_MODULE_SCHEMA
    assert result["module_id"] == "routing-semantic-v1-oracle"
    assert result["study_id"] == "routing-semantic-v1"
    assert result["primary_roles"] == ["A", "B"]
    assert result["adjudicator_ids"] == ["codex-a", "codex-b", "codex-c"]
    assert result["shared_frozen_ab_inputs"] == ["oracle-view"]
    assert len(result["module_sha256"]) == 64
    assert result["guardrails"]["repository_mounted"] is False
    assert result["guardrails"]["cross_agent_visibility"] is False


def test_module_requires_distinct_adjudicator_ids(tmp_path: Path):
    def mutate(value):
        value["roles"]["tiebreaker"]["adjudicator_id"] = "codex-a"

    path = _copy_module(tmp_path, mutate)
    with pytest.raises(WorkflowError, match="must be distinct"):
        validate_abc_adjudication_module(path)


def test_module_requires_hash_pinned_shared_ab_input(tmp_path: Path):
    def mutate(value):
        for item in value["required_files"]:
            if {"A", "B"}.issubset(set(item["roles"])):
                item["sha256"] = None

    path = _copy_module(tmp_path, mutate)
    with pytest.raises(WorkflowError, match="hash-pinned"):
        validate_abc_adjudication_module(path)


def test_module_rejects_unsafe_result_path(tmp_path: Path):
    def mutate(value):
        value["results"]["runtime_root"] = "../shared"

    path = _copy_module(tmp_path, mutate)
    with pytest.raises(WorkflowError, match="safe relative path"):
        validate_abc_adjudication_module(path)
