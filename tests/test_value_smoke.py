from __future__ import annotations

from pathlib import Path

from agent_workflow_benchmark.benchmarking.contracts import (
    BENCHMARK_SPEC_V3_SCHEMA,
    normalized_arm_profiles,
    validate_spec,
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
