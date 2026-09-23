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
import agent_workflow_benchmark.benchmarking.planning as benchmark_planning
import agent_workflow_benchmark.benchmarking.service as benchmark_service
from agent_workflow_benchmark.benchmarking.service import (
    export_bm4_optimized_suite,
    export_structured_value_smoke_suite,
    export_value_smoke_suite,
)


def test_toolchain_identity_prefers_stack_install_provenance(tmp_path: Path, monkeypatch) -> None:
    import json

    venv = tmp_path / "venv"
    provenance = venv / "share" / "agent-workflow" / "source-provenance.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(
        json.dumps(
            {
                "schema": "agent-workflow/source-provenance/v1",
                "components": {
                    "agent-workflow-benchmark": {
                        "version": "0.3.1",
                        "revision": "a" * 40,
                        "dirty": False,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(benchmark_planning.sys, "prefix", str(venv))
    monkeypatch.setattr(
        benchmark_planning,
        "TOOLCHAIN_DISTRIBUTIONS",
        ("agent-workflow-benchmark",),
    )
    monkeypatch.setattr(
        benchmark_planning,
        "_distribution_identity",
        lambda _name, fallback_root=None: {
            "version": "0.3.1",
            "editable": False,
            "source_revision": None,
            "source_dirty": None,
        },
    )

    identity = benchmark_planning._toolchain_identity()["agent-workflow-benchmark"]

    assert identity["source_revision"] == "a" * 40
    assert identity["source_dirty"] is False
    assert identity["source_provenance"] == "stack-install-manifest"


def test_generic_priority_picker_export_uses_future_gpt6_model(tmp_path: Path) -> None:
    import json

    destination = tmp_path / "suite"
    benchmark_service.export_builtin_suite(
        destination,
        benchmark_id="priority-picker-v2",
    )
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )

    assert executor["model"] == "gpt-6-luna"
    assert executor["price_catalog_id"] is None
    assert executor["pricing"] is None


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
    assert not (destination / "executors" / "claude-subscription.json").exists()
    assert (destination / "executors" / "codex-subscription.json").is_file()
    assert result["default_subscription_executors"] == [
        str(destination / "executors" / "codex-subscription.json")
    ]
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    assert executor["model"] == "gpt-5.6-luna"
    assert executor["price_catalog_id"] == "openai-gpt-5.6-standard-20260802"



def test_structured_bm3_export_is_structured_direct_vs_agent_workflow(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_structured_value_smoke_suite(destination)

    spec = validate_spec(Path(result["spec"]))
    profiles = normalized_arm_profiles(spec)

    assert spec["schema"] == BENCHMARK_SPEC_V3_SCHEMA
    assert result["study"] == "structured-direct-vs-agent-workflow-full"
    assert profiles["control_raw"]["treatment_id"] == "structured-direct/v1"
    assert profiles["control_raw"]["runner"]["kind"] == "direct-executor"
    assert profiles["workflow_full"]["treatment_id"] == "agent-workflow-full/v1"
    assert profiles["workflow_full"]["runner"]["kind"] == "agent-workflow"
    assert profiles["workflow_full"]["runner"]["agent_class"] == "implementation"
    assert spec["arms"]["control"]["wrapper_path"] == spec["arms"]["candidate"]["wrapper_path"]
    assert spec["arms"]["control"]["wrapper_path"].endswith("profiles/workflow_full.md")
    assert not (destination / "executors" / "claude-subscription.json").exists()
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    assert executor["model"] == "gpt-5.6-luna"
    assert executor["price_catalog_id"] == "openai-gpt-5.6-standard-20260802"


def test_bm4_export_uses_gpt6_high_and_optimized_treatment(tmp_path: Path) -> None:
    import json

    destination = tmp_path / "bm4-suite"
    result = export_bm4_optimized_suite(destination)

    spec = validate_spec(Path(result["spec"]))
    profiles = normalized_arm_profiles(spec)
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )

    assert result["study"] == "bm4-structured-direct-vs-agent-workflow-optimized"
    assert result["model"] == "gpt-6-luna"
    assert result["effort"] == "high"
    assert result["optimizations"] == [f"OPT-{index:03d}" for index in range(1, 8)]
    assert executor["model"] == "gpt-6-luna"
    assert executor["effort"] == "high"
    assert profiles["control_raw"]["treatment_id"] == "structured-direct/v1"
    assert profiles["control_raw"]["runner"]["kind"] == "direct-executor"
    assert profiles["workflow_full"]["treatment_id"] == "agent-workflow-optimized/v1"
    assert profiles["workflow_full"]["runner"]["kind"] == "agent-workflow"
    assert profiles["workflow_full"]["runner"]["agent_class"] == "implementation"
    enabled = set(spec["arms"]["candidate"]["enabled_features"])
    assert "compact executor-context projection (OPT-001/004/007)" in enabled
    assert "implementation amplification telemetry (OPT-002/003)" in enabled
    assert "host-owned deterministic gates (OPT-005)" in enabled
    assert "unchanged-workspace verification reuse (OPT-006)" in enabled


def test_value_smoke_export_accepts_agent_class_override(tmp_path: Path) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(
        destination,
        agent_class="benchmark-implementation",
    )

    spec = validate_spec(Path(result["spec"]))
    assert spec["arms"]["candidate"]["runner"]["agent_class"] == "benchmark-implementation"


def test_agent_workflow_runner_maps_codex_executor_id() -> None:
    assert AGENT_WORKFLOW_EXECUTOR_ALIASES["codex-cli"] == "codex"


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


def test_execution_only_readiness_skips_visual_attestation(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    monkeypatch.setattr(
        benchmark_service,
        "preflight_authentication",
        lambda configured: {"authenticated": True, "detail": "test authenticated"},
    )
    monkeypatch.setattr(benchmark_service.shutil, "which", lambda name: f"/usr/bin/{name}")

    readiness = benchmark_service.benchmark_readiness(
        Path(result["spec"]),
        destination / "executors" / "codex-subscription.json",
        policy=destination / "policies" / "development.json",
        settings=defaults(),
        execution_only=True,
    )
    by_id = {item["id"]: item for item in readiness["checks"]}

    assert readiness["ready"] is True
    assert readiness["execution_ready"] is True
    assert readiness["full_pipeline_ready"] is False
    assert readiness["runtime"]["runtime_state"] == "not-required"
    assert by_id["visual-runtime"]["passed"] is True
    assert "not required for execution-only" in by_id["visual-runtime"]["detail"]


def test_typesafe_runtime_check_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    spec = validate_spec(Path(result["spec"]))
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        "agent_workflow.semantic.typesafe.capability",
        lambda settings: {
            "provider": "typesafe",
            "typesafe_sdk_installed": True,
            "api_key_configured": False,
            "model": None,
        },
    )
    settings = replace(defaults(), decision_mode="typesafe")

    checks = treatment_runtime_checks(settings, spec, executor)
    by_id = {item["id"]: item for item in checks}

    assert by_id["typesafe-sdk"]["passed"] is True
    assert by_id["typesafe-api-key"]["passed"] is False


def test_comparative_runtime_check_requires_shared_library(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "suite"
    result = export_value_smoke_suite(destination)
    spec = validate_spec(Path(result["spec"]))
    import json
    executor = json.loads(
        (destination / "executors" / "codex-subscription.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        "agent_workflow.semantic.typesafe.capability",
        lambda settings: {
            "provider": "typesafe",
            "typesafe_sdk_installed": True,
            "api_key_configured": True,
            "model": None,
        },
    )
    monkeypatch.setattr(
        "agent_workflow.comparative_eval.shared_library_status",
        lambda: {
            "installed": True,
            "compatible": False,
            "version": "0.0.0",
            "distribution": "agent-workflow-comparative-eval",
        },
    )
    settings = replace(defaults(), decision_mode="comparative")

    checks = treatment_runtime_checks(settings, spec, executor)
    by_id = {item["id"]: item for item in checks}

    assert by_id["typesafe-api-key"]["passed"] is True
    assert by_id["comparative-eval"]["passed"] is False
