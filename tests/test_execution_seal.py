from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.execution_seal import (
    seal_execution,
    verify_execution_seal,
)
from agent_workflow_benchmark.benchmarking.scoring import score_run


def _fake_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps({"state": "executed"}),
        encoding="utf-8",
    )
    pairs = []
    arms = {}
    for arm_name in ("control_raw", "workflow_full"):
        worktree = tmp_path / arm_name
        worktree.mkdir()
        (worktree / "result.txt").write_text(f"{arm_name}\n", encoding="utf-8")
        stage = worktree / ".agent-workflow-benchmark" / "stage"
        stage.mkdir(parents=True)
        (stage / "arm.json").write_text(
            json.dumps({"state": "completed", "arm": arm_name}),
            encoding="utf-8",
        )
        phase = stage / "phases" / "implement"
        phase.mkdir(parents=True)
        (phase / "phase.json").write_text(
            json.dumps({"state": "completed"}),
            encoding="utf-8",
        )
        arms[arm_name] = {
            "worktree": str(worktree),
            "stage_dir": str(stage),
        }
    pairs.append(
        {
            "pair_id": "pair-01",
            "case_id": "case-01",
            "repetition": 1,
            "attempts": [
                {
                    "attempt": 1,
                    "arms": arms,
                }
            ],
        }
    )
    plan = {
        "run_id": "seal-test",
        "benchmark_id": "blind-task-v1",
        "coordinator": {"run_dir": str(run_dir)},
        "pairs": pairs,
    }
    plan_path = run_dir / "run-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan_path


def test_execution_seal_freezes_worktrees_and_execution_evidence(tmp_path: Path) -> None:
    plan = _fake_run(tmp_path)

    seal = seal_execution(plan)
    assert seal["schema"] == "agent-workflow/benchmark-execution-seal/v1"
    assert len(seal["arms"]) == 2

    verification = verify_execution_seal(plan)
    assert verification["valid"] is True
    assert verification["sealed"] is True

    (tmp_path / "control_raw" / "result.txt").write_text(
        "mutated after seal\n",
        encoding="utf-8",
    )
    verification = verify_execution_seal(plan)
    assert verification["valid"] is False
    assert any("worktree changed after seal" in item for item in verification["mismatches"])


def test_scoring_requires_execution_seal(tmp_path: Path) -> None:
    plan = _fake_run(tmp_path)

    with pytest.raises(WorkflowError, match="requires a valid execution seal"):
        score_run(plan)


def test_execution_seal_must_precede_scoring(tmp_path: Path) -> None:
    plan = _fake_run(tmp_path)
    run_dir = plan.parent
    (run_dir / "machine-scores.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(WorkflowError, match="sealed before machine scoring"):
        seal_execution(plan)
