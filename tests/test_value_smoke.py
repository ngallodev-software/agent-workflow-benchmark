from __future__ import annotations

from dataclasses import replace
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
    uses_agent_workflow,
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


def test_direct_only_v3_does_not_require_agent_workflow_runtime(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    spec = validate_spec(Path(result["spec"]))
    spec["arms"]["candidate"]["runner"] = {
        "kind": "direct-executor",
        "agent_class": None,
    }

    assert uses_agent_workflow(spec) is False
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    assert treatment_runtime_checks(defaults(), spec, executor) == []


def test_runtime_checks_reject_different_provider_executable(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    spec = validate_spec(Path(result["spec"]))
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    base = defaults()
    mismatched = replace(
        base,
        executors={**base.executors, "codex": ["codex-wrapper", "exec", "-"]},
    )

    checks = treatment_runtime_checks(mismatched, spec, executor)
    by_id = {item["id"]: item for item in checks}

    assert by_id["agent-workflow-executable"]["passed"] is False
