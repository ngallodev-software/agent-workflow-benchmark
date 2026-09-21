from __future__ import annotations

from pathlib import Path

from agent_workflow_benchmark.benchmarking.contracts import (
    BENCHMARK_SPEC_V3_SCHEMA,
    normalized_arm_profiles,
    validate_spec,
)
from agent_workflow.config import defaults
from agent_workflow_benchmark.benchmarking.treatments import (
    AGENT_WORKFLOW_EXECUTOR_ALIASES,
    treatment_runtime_checks,
)
from agent_workflow_benchmark.benchmarking.service import export_value_smoke_suite


def test_value_smoke_export_uses_explicit_treatments(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)

    spec = validate_spec(Path(result["spec"]))
    profiles = normalized_arm_profiles(spec)

    assert spec["schema"] == BENCHMARK_SPEC_V3_SCHEMA
    assert set(spec["arms"]) == {"control", "candidate"}
    assert profiles["control_raw"]["treatment_id"] == "raw-direct/v1"
    assert profiles["control_raw"]["runner"]["kind"] == "direct-executor"
    assert profiles["workflow_full"]["treatment_id"] == "agent-workflow-full/v1"
    assert profiles["workflow_full"]["runner"]["kind"] == "agent-workflow"
    assert profiles["workflow_full"]["runner"]["agent_class"] == "implementation"


def test_value_smoke_export_accepts_agent_class_override(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(
        destination,
        agent_class="benchmark-implementation",
    )

    spec = validate_spec(Path(result["spec"]))
    assert spec["arms"]["candidate"]["runner"]["agent_class"] == "benchmark-implementation"


def test_agent_workflow_runner_maps_builtin_executor_ids() -> None:
    assert AGENT_WORKFLOW_EXECUTOR_ALIASES["codex-cli"] == "codex"
    assert AGENT_WORKFLOW_EXECUTOR_ALIASES["claude-code-cli"] == "claude"


def test_value_smoke_runtime_checks_match_default_codex_binding(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    spec = validate_spec(Path(result["spec"]))
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )

    checks = treatment_runtime_checks(defaults(), spec, executor)

    assert checks
    assert all(item["passed"] for item in checks), checks
