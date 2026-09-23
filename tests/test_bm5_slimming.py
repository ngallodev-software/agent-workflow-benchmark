from __future__ import annotations

import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.runner import (
    _bm5_acceptance_commands,
    _bm5_should_skip_verify,
)
from agent_workflow_benchmark.benchmarking.service import export_bm5_slimmed_suite


def test_bm5_export_declares_steering_first_fast_path(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_bm5_slimmed_suite(destination, agent_class="implementation")
    spec = json.loads((destination / "benchmark-spec.json").read_text(encoding="utf-8"))
    candidate = spec["arms"]["candidate"]

    assert result["study"] == "bm5-structured-direct-vs-agent-workflow-slimmed"
    assert result["model"] == "gpt-6-luna"
    assert result["effort"] == "high"
    assert candidate["treatment_id"] == "agent-workflow-bm5/v1"
    assert candidate["runner"] == {
        "kind": "agent-workflow",
        "agent_class": "implementation",
    }
    text = "\n".join(candidate["enabled_features"])
    assert "single agent-finish closeout transaction (OPT-010/011)" in text
    assert "host-derived acceptance criteria (OPT-012)" in text
    assert "steering-first exceptional worker protocol (OPT-013)" in text
    assert "per-command/cache amplification telemetry (OPT-014)" in text
    assert "conditional verify/repair model invocation (OPT-015)" in text


def test_bm5_acceptance_commands_are_phase_specific() -> None:
    analyze = _bm5_acceptance_commands("analyze-plan")
    implement = _bm5_acceptance_commands("implement")
    verify = _bm5_acceptance_commands("verify-repair")

    assert [item["id"] for item in analyze] == ["plan-present"]
    assert "BENCHMARK_PLAN.md" in " ".join(analyze[0]["argv"])
    assert implement == verify
    assert implement[0]["argv"] == [
        "python", "-m", "unittest", "discover", "-s", "tests/public", "-v"
    ]


def test_bm5_verify_phase_skips_only_after_completed_implementation(tmp_path: Path) -> None:
    arm = {
        "arm": "workflow_full",
        "stage_dir": str(tmp_path / "stage"),
    }
    plan = {
        "treatments": {
            "workflow_full": {
                "runner_kind": "agent-workflow",
                "treatment_id": "agent-workflow-bm5/v1",
            }
        }
    }
    verify = {"id": "verify-repair"}

    phase_dir = tmp_path / "stage" / "phases" / "implement"
    phase_dir.mkdir(parents=True)
    (phase_dir / "phase.json").write_text(
        json.dumps({"state": "task_failed"}), encoding="utf-8"
    )
    assert _bm5_should_skip_verify(plan, arm, verify) is False

    (phase_dir / "phase.json").write_text(
        json.dumps({"state": "completed"}), encoding="utf-8"
    )
    assert _bm5_should_skip_verify(plan, arm, verify) is True

    bm4 = {
        "treatments": {
            "workflow_full": {
                "runner_kind": "agent-workflow",
                "treatment_id": "agent-workflow-optimized/v1",
            }
        }
    }
    assert _bm5_should_skip_verify(bm4, arm, verify) is False
