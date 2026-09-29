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


def test_routing_semantic_v2_module_pair_binds_frozen_inputs():
    direct = ROOT / "modules" / "abc-adjudication" / "routing-semantic-v2.module.json"
    inspect = (
        ROOT
        / "modules"
        / "abc-adjudication"
        / "routing-semantic-v2.inspect.module.json"
    )
    direct_value = json.loads(direct.read_text(encoding="utf-8"))
    inspect_value = json.loads(inspect.read_text(encoding="utf-8"))

    assert validate_abc_adjudication_module(direct)["valid"] is True
    assert validate_abc_adjudication_module(inspect)["valid"] is True
    assert direct_value["task"] == inspect_value["task"]
    assert direct_value["prompt"]["template"] == "docker/adjudication/START_PROMPT.v2.template.md"
    assert inspect_value["prompt"]["template"] == direct_value["prompt"]["template"]
    assert direct_value["output"]["pass_schema"].endswith("/v2")
    assert inspect_value["output"]["pass_schema"] == direct_value["output"]["pass_schema"]

    direct_files = {item["id"]: item for item in direct_value["required_files"]}
    inspect_files = {item["id"]: item for item in inspect_value["required_files"]}
    expected = {
        "oracle-view": "88a18b5e1a1132a25da41bee5fabbeeaa8a687be395fc28bd39c0b4d6a9a2617",
        "oracle-protocol": "ff165c964fd032e95160ff760a0f46e661e88d41fd22a376f9b0767e24ba793e",
        "routing-corpus": "99f113ce05c2921a45534e3e7cf17f410379589208cf95415a57c47caff61236",
    }
    for file_id, digest in expected.items():
        assert direct_files[file_id]["sha256"] == digest
        assert inspect_files[file_id]["sha256"] == digest


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
