from __future__ import annotations

import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.contracts import validate_spec
from agent_workflow_benchmark.benchmarking.service import export_bm6_blind_suite


def test_bm6_export_is_blind_and_uses_new_task_family(tmp_path: Path) -> None:
    destination = tmp_path / "bm6"
    result = export_bm6_blind_suite(destination)

    spec = validate_spec(destination / "benchmark-spec.json")
    contract = json.loads(
        (destination / "scoring-contract.json").read_text(encoding="utf-8")
    )
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(
            encoding="utf-8"
        )
    )
    runtime = json.loads(
        (destination / "visual-runtime-lock.json").read_text(encoding="utf-8")
    )

    assert result["benchmark_id"] == "change-window-v1"
    assert result["blind_execution"] is True
    assert result["scoring_mode"] == "external-post-seal"
    assert spec["benchmark_id"] == "change-window-v1"
    assert spec["arms"]["control"]["treatment_id"] == "structured-direct/v1"
    assert spec["arms"]["candidate"]["treatment_id"] == "agent-workflow-bm5/v1"
    assert executor["model"] == "gpt-6-luna"
    assert executor["effort"] == "high"
    assert runtime["browser_version"] == "151.0.7922.173"

    assert contract["evaluator_path"] == "external://score.py"
    assert not (destination / "evaluation").exists()
    assert not (destination / "executors" / "solutions").exists()
    assert list(destination.rglob("score.py")) == []
    assert not (destination / "product-scoring-contract.json").exists()

    task = (destination / "canonical-task.md").read_text(encoding="utf-8")
    assert "Change Window Planner" in task
    assert "Priority Picker" not in task


def test_bm6_agent_class_override(tmp_path: Path) -> None:
    destination = tmp_path / "bm6"
    export_bm6_blind_suite(
        destination,
        agent_class="benchmark-implementation",
    )
    spec = json.loads(
        (destination / "benchmark-spec.json").read_text(encoding="utf-8")
    )
    assert (
        spec["arms"]["candidate"]["runner"]["agent_class"]
        == "benchmark-implementation"
    )
