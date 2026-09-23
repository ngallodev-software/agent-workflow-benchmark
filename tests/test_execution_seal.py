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

    arms = {}
    for arm_name in ("control_raw", "workflow_full"):
        worktree = tmp_path / arm_name
        worktree.mkdir()
        (worktree / "result.txt").write_text(f"{arm_name}\n", encoding="utf-8")
        stage = worktree / ".awb"
        stage.mkdir(parents=True)
        (stage / "arm.json").write_text(
            json.dumps({
                "state": "completed",
                "arm": arm_name,
                "worktree": str(worktree),
                "stage_dir": str(stage),
            }),
            encoding="utf-8",
        )
        phase = stage / "ph" / "p2"
        phase.mkdir(parents=True)
        (phase / "phase.json").write_text(
            json.dumps({"state": "completed"}),
            encoding="utf-8",
        )
        arms[arm_name] = {
            "worktree": str(worktree),
            "stage_dir": str(stage),
        }

    pair_state = run_dir / "ps" / "p-test"
    attempt_state = pair_state / "a01"
    attempt_state.mkdir(parents=True)
    attempt_receipt = {
        "attempt": 1,
        "attempt_id": "pair-01-a01",
        "state": "terminal",
        "arms": {
            name: str(Path(value["stage_dir"]) / "arm.json")
            for name, value in arms.items()
        },
    }
    attempt_path = attempt_state / "attempt.json"
    attempt_path.write_text(json.dumps(attempt_receipt), encoding="utf-8")
    pair_receipt = {
        "pair_id": "pair-01",
        "case_id": "case-01",
        "repetition": 1,
        "selected_attempt": 1,
        "attempts": [{
            "attempt": 1,
            "attempt_id": "pair-01-a01",
            "state": "terminal",
            "evidence": str(attempt_path),
        }],
        "arms": attempt_receipt["arms"],
    }
    (pair_state / "pair.json").write_text(
        json.dumps(pair_receipt),
        encoding="utf-8",
    )

    # Attempt 2 is planned/reserved but deliberately never executed.
    unused_arms = {
        name: {
            "worktree": str(tmp_path / "unused" / name),
            "stage_dir": str(tmp_path / "unused" / name / ".awb"),
        }
        for name in ("control_raw", "workflow_full")
    }
    pairs = [{
        "pair_id": "pair-01",
        "case_id": "case-01",
        "repetition": 1,
        "attempts": [
            {
                "attempt": 1,
                "attempt_id": "pair-01-a01",
                "arms": arms,
            },
            {
                "attempt": 2,
                "attempt_id": "pair-01-a02",
                "arms": unused_arms,
            },
        ],
    }]
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
    assert len(seal["executed_pairs"]) == 1
    assert [item["attempt"] for item in seal["executed_pairs"][0]["attempts"]] == [1]

    verification = verify_execution_seal(plan)
    assert verification["valid"] is True
    assert verification["sealed"] is True

    # Host-managed post-seal scoring output must not alter the sealed task worktree.
    scores = tmp_path / "control_raw" / ".awb" / "scores"
    scores.mkdir()
    (scores / "score.json").write_text("{}\n", encoding="utf-8")
    verification = verify_execution_seal(plan)
    assert verification["valid"] is True

    (tmp_path / "control_raw" / "result.txt").write_text(
        "mutated after seal\n",
        encoding="utf-8",
    )
    verification = verify_execution_seal(plan)
    assert verification["valid"] is False
    assert any("worktree changed after seal" in item for item in verification["mismatches"])


def test_execution_seal_rejects_missing_executed_arm_receipt(tmp_path: Path) -> None:
    plan = _fake_run(tmp_path)
    (tmp_path / "control_raw" / ".awb" / "arm.json").unlink()

    with pytest.raises(WorkflowError, match="executed arm evidence is incomplete"):
        seal_execution(plan)


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
