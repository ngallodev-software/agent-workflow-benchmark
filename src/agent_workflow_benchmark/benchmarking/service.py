from __future__ import annotations

from pathlib import Path, PurePosixPath
import json
import shutil
import time
from typing import Any

from ..assets import asset_path, copy_asset_tree
from agent_workflow.config import Settings
from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run as run_process
from agent_workflow.util import atomic_write_json, utc_now
from .common import read_object, tree_sha256, write_manifest
from .auth import preflight_authentication
from .policy import apply_operating_policy, implicit_operating_policy, load_operating_policy
from .pairing import attempts_for
from .runtime import attest_runtime, seal_runtime_lock, validate_runtime_lock
from .treatments import treatment_runtime_checks, uses_agent_workflow
from .consolidation import consolidate_run, verify_consolidated_run
from .contracts import BENCHMARK_SPEC_V3_SCHEMA, validate_executor_config, validate_spec
from .planning import create_run_plan, materialize_fixture
from .runner import execute_run
from .scoring import score_run
from .execution_seal import seal_execution, verify_execution_seal


def _resolve_plan(settings: Settings, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        if candidate.is_dir():
            candidate = candidate / "run-plan.json"
        return candidate.resolve()
    run_id = str(value)
    candidate = settings.worktree_root / "benchmarks" / run_id / "coordinator" / "benchmarks" / "runs" / run_id / "run-plan.json"
    if candidate.is_file():
        return candidate.resolve()
    raise WorkflowError(f"benchmark run not found: {value}")


def validate_benchmark(spec: Path, executor: Path | None = None) -> dict[str, Any]:
    value = validate_spec(spec)
    result = {
        "benchmark_id": value["benchmark_id"],
        "version": value["version"],
        "cases": [item["id"] for item in value["cases"]],
        "phases": [item["id"] for item in value["phases"]],
        "machine_points": sum(item["max_points"] for item in value["machine_scoring"]["scorers"]),
        "arms": sorted(value["arms"]),
    }
    if executor is not None:
        configured = validate_executor_config(executor)
        result["executor"] = {
            "provider": configured["provider"],
            "executor": configured["executor"],
            "version": configured["executor_version"],
            "model": configured["model"],
            "authentication_mode": configured["authentication"]["mode"],
            "billing_mode": configured["billing"]["mode"],
        }
    return result


BUILTIN_BENCHMARK_LAYOUT_SCHEMA = "agent-workflow/builtin-benchmark-layout/v1"


def _validate_builtin_layer(value: object, benchmark_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: layout layer must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorkflowError(f"built-in benchmark {benchmark_id}: invalid layout layer: {value}")
    if not path.parts or path.parts[0] != "_shared":
        raise WorkflowError(f"built-in benchmark {benchmark_id}: layout layers must live under _shared/: {value}")
    return value


def materialize_builtin_suite(destination: Path, benchmark_id: str) -> Path:
    """Materialize a self-contained built-in benchmark suite from shared layers.

    The packaged benchmark assets are stored as immutable shared layers plus
    suite-specific overlays.  Consumers never need to understand that storage
    format: materialization reproduces the complete historical suite tree.
    """
    if not benchmark_id or any(part in {"", ".", ".."} for part in Path(benchmark_id).parts) or Path(benchmark_id).name != benchmark_id:
        raise WorkflowError(f"invalid built-in benchmark suite ID: {benchmark_id}")
    suite_relative = f"benchmarks/{benchmark_id}"
    source = asset_path(suite_relative)
    if not source.is_dir():
        raise WorkflowError(f"unknown built-in benchmark suite: {benchmark_id}")
    layout_asset = asset_path(f"{suite_relative}/suite-layout.json")
    if not layout_asset.is_file():
        raise WorkflowError(f"built-in benchmark {benchmark_id}: suite-layout.json is required")
    try:
        layout = json.loads(layout_asset.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: invalid suite-layout.json: {exc}") from exc
    if not isinstance(layout, dict) or layout.get("schema") != BUILTIN_BENCHMARK_LAYOUT_SCHEMA:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: unsupported suite layout schema")
    if layout.get("benchmark_id") != benchmark_id:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: suite layout benchmark_id mismatch")
    raw_layers = layout.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: suite layout requires at least one shared layer")
    expected_tree_sha256 = layout.get("materialized_tree_sha256")
    if not isinstance(expected_tree_sha256, str) or len(expected_tree_sha256) != 64:
        raise WorkflowError(f"built-in benchmark {benchmark_id}: materialized_tree_sha256 is required")

    destination.mkdir(parents=True, exist_ok=True)
    for raw_layer in raw_layers:
        layer = _validate_builtin_layer(raw_layer, benchmark_id)
        layer_asset = asset_path(f"benchmarks/{layer}")
        if not layer_asset.is_dir():
            raise WorkflowError(f"built-in benchmark {benchmark_id}: missing shared layer: {layer}")
        copy_asset_tree(f"benchmarks/{layer}", destination)
    copy_asset_tree(suite_relative, destination)
    (destination / "suite-layout.json").unlink(missing_ok=True)
    observed_tree_sha256 = tree_sha256(destination)
    if observed_tree_sha256 != expected_tree_sha256:
        raise WorkflowError(
            f"built-in benchmark {benchmark_id}: materialized suite digest mismatch; "
            f"expected {expected_tree_sha256}, observed {observed_tree_sha256}"
        )
    return destination


def export_builtin_suite(
    destination: Path,
    *,
    benchmark_id: str = "priority-picker-v1",
    force: bool = False,
) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise WorkflowError(f"benchmark suite destination already exists: {destination}")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    materialize_builtin_suite(destination, benchmark_id)
    spec = destination / "benchmark-spec.json"
    synthetic = destination / "executors" / "synthetic.json"
    validate_spec(spec)
    validate_executor_config(synthetic)
    executors = sorted(str(path) for path in (destination / "executors").glob("*.json"))
    return {
        "benchmark_id": benchmark_id,
        "destination": str(destination),
        "spec": str(spec),
        "synthetic_executor": str(synthetic),
        "executors": executors,
        "default_authentication": "subscription-session",
        "supported_authentication": ["subscription-session"],
        "test_only_authentication": ["synthetic-none"],
        "operating_policies": sorted(str(path) for path in (destination / "policies").glob("*.json")),
        "default_subscription_executors": [
            str(destination / "executors" / "codex-subscription.json"),
            str(destination / "executors" / "claude-subscription.json"),
        ],
    }


HISTORICAL_CODEX_MODEL = "gpt-5.6-luna"
HISTORICAL_CODEX_PRICE_CATALOG = "openai-gpt-5.6-standard-20260802"
HISTORICAL_CODEX_PRICING = {
    "input_tokens_include_cached": True,
    "usd_per_million_tokens": {
        "input": 0.2,
        "cached_input": 0.02,
        "cache_write_input": 0.25,
        "output": 1.2,
        "reasoning_output": 0,
    },
}


def _pin_historical_codex_executor(destination: Path) -> None:
    path = destination / "executors" / "codex-subscription.json"
    value = read_object(path)
    value["model"] = HISTORICAL_CODEX_MODEL
    value["currency"] = "USD"
    value["price_catalog_id"] = HISTORICAL_CODEX_PRICE_CATALOG
    value["pricing"] = HISTORICAL_CODEX_PRICING
    atomic_write_json(path, value)
    validate_executor_config(path)


def export_value_smoke_suite(
    destination: Path,
    *,
    force: bool = False,
    agent_class: str = "implementation",
) -> dict[str, Any]:
    """Export the first raw-direct vs real Agent-Workflow value smoke study."""
    result = export_builtin_suite(
        destination,
        benchmark_id="priority-picker-v2",
        force=force,
    )
    _pin_historical_codex_executor(destination)
    # The value smoke is deliberately Codex-only. Keep generic Claude support
    # in normal benchmark suites, but do not ship an alternate smoke executor.
    claude_profile = destination / "executors" / "claude-subscription.json"
    claude_profile.unlink(missing_ok=True)
    result["executors"] = [
        item for item in result.get("executors", [])
        if not str(item).endswith("claude-subscription.json")
    ]
    result["default_subscription_executors"] = [
        str(destination / "executors" / "codex-subscription.json")
    ]
    spec_path = Path(result["spec"])
    spec = read_object(spec_path)
    legacy_raw = dict(spec["arms"]["control_raw"])
    spec["schema"] = BENCHMARK_SPEC_V3_SCHEMA
    spec["arms"] = {
        "control": {
            **legacy_raw,
            "profile_id": "raw-direct/v1",
            "treatment_id": "raw-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
        "candidate": {
            **legacy_raw,
            "profile_id": "agent-workflow-full/v1",
            "treatment_id": "agent-workflow-full/v1",
            "runner": {"kind": "agent-workflow", "agent_class": agent_class},
            "enabled_features": [
                "canonical task prompts",
                "benchmark-neutral safety envelope",
                "Agent-Workflow Agent Run lifecycle",
                "Agent-Workflow durable execution state",
                "Agent-Workflow completion evidence and sealing",
            ],
            "disabled_features": [],
        },
    }
    atomic_write_json(spec_path, spec)
    validate_spec(spec_path)
    result.update(
        study="raw-direct-vs-agent-workflow-full",
        schema=BENCHMARK_SPEC_V3_SCHEMA,
        agent_class=agent_class,
    )
    return result


def export_structured_value_smoke_suite(
    destination: Path,
    *,
    force: bool = False,
    agent_class: str = "implementation",
) -> dict[str, Any]:
    """Export structured-direct vs real Agent-Workflow BM3 study.

    Both treatments receive the same structured workflow wrapper. The control
    executes it directly through the provider CLI; the candidate executes the
    same prompt through the real Agent-Workflow Agent Run lifecycle. This
    isolates lifecycle/orchestration overhead from prompt-discipline effects.
    """
    result = export_builtin_suite(
        destination,
        benchmark_id="priority-picker-v2",
        force=force,
    )
    _pin_historical_codex_executor(destination)
    claude_profile = destination / "executors" / "claude-subscription.json"
    claude_profile.unlink(missing_ok=True)
    result["executors"] = [
        item for item in result.get("executors", [])
        if not str(item).endswith("claude-subscription.json")
    ]
    result["default_subscription_executors"] = [
        str(destination / "executors" / "codex-subscription.json")
    ]
    spec_path = Path(result["spec"])
    spec = read_object(spec_path)
    structured_profile = dict(spec["arms"]["workflow_full"])
    spec["schema"] = BENCHMARK_SPEC_V3_SCHEMA
    spec["arms"] = {
        "control": {
            **structured_profile,
            "profile_id": "structured-direct/v1",
            "treatment_id": "structured-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
        "candidate": {
            **structured_profile,
            "profile_id": "agent-workflow-full/v1",
            "treatment_id": "agent-workflow-full/v1",
            "runner": {"kind": "agent-workflow", "agent_class": agent_class},
            "enabled_features": [
                *structured_profile.get("enabled_features", []),
                "Agent-Workflow Agent Run lifecycle",
                "Agent-Workflow durable execution state",
                "Agent-Workflow completion evidence and sealing",
            ],
            "disabled_features": [],
        },
    }
    atomic_write_json(spec_path, spec)
    validate_spec(spec_path)
    result.update(
        study="structured-direct-vs-agent-workflow-full",
        schema=BENCHMARK_SPEC_V3_SCHEMA,
        agent_class=agent_class,
    )
    return result


def export_bm4_optimized_suite(
    destination: Path,
    *,
    force: bool = False,
    agent_class: str = "implementation",
) -> dict[str, Any]:
    """Export BM4: GPT-6 Luna structured direct vs optimized Agent-Workflow."""
    result = export_builtin_suite(
        destination,
        benchmark_id="priority-picker-v2",
        force=force,
    )
    # Unlike BM3, BM4 intentionally keeps the current future-facing executor
    # profile: gpt-6-luna/high for both paired arms.
    claude_profile = destination / "executors" / "claude-subscription.json"
    claude_profile.unlink(missing_ok=True)
    result["executors"] = [
        item for item in result.get("executors", [])
        if not str(item).endswith("claude-subscription.json")
    ]
    result["default_subscription_executors"] = [
        str(destination / "executors" / "codex-subscription.json")
    ]
    spec_path = Path(result["spec"])
    spec = read_object(spec_path)
    structured_profile = dict(spec["arms"]["workflow_full"])
    spec["schema"] = BENCHMARK_SPEC_V3_SCHEMA
    spec["arms"] = {
        "control": {
            **structured_profile,
            "profile_id": "structured-direct/v1",
            "treatment_id": "structured-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
        "candidate": {
            **structured_profile,
            "profile_id": "agent-workflow-optimized/v1",
            "treatment_id": "agent-workflow-optimized/v1",
            "runner": {"kind": "agent-workflow", "agent_class": agent_class},
            "enabled_features": [
                *structured_profile.get("enabled_features", []),
                "Agent-Workflow Agent Run lifecycle",
                "compact executor-context projection (OPT-001/004/007)",
                "implementation amplification telemetry (OPT-002/003)",
                "host-owned deterministic gates (OPT-005)",
                "unchanged-workspace verification reuse (OPT-006)",
            ],
            "disabled_features": [],
        },
    }
    atomic_write_json(spec_path, spec)
    validate_spec(spec_path)
    result.update(
        study="bm4-structured-direct-vs-agent-workflow-optimized",
        schema=BENCHMARK_SPEC_V3_SCHEMA,
        agent_class=agent_class,
        model="gpt-6-luna",
        effort="high",
        optimizations=[f"OPT-{index:03d}" for index in range(1, 8)],
    )
    return result


def export_bm5_slimmed_suite(
    destination: Path,
    *,
    force: bool = False,
    agent_class: str = "implementation",
) -> dict[str, Any]:
    """Export BM5: GPT-6 Luna direct vs steering-first Agent-Workflow fast path."""
    result = export_builtin_suite(
        destination,
        benchmark_id="priority-picker-v3",
        force=force,
    )
    claude_profile = destination / "executors" / "claude-subscription.json"
    claude_profile.unlink(missing_ok=True)
    result["executors"] = [
        item for item in result.get("executors", [])
        if not str(item).endswith("claude-subscription.json")
    ]
    result["default_subscription_executors"] = [
        str(destination / "executors" / "codex-subscription.json")
    ]
    spec_path = Path(result["spec"])
    spec = read_object(spec_path)
    structured_profile = dict(spec["arms"]["workflow_full"])
    spec["schema"] = BENCHMARK_SPEC_V3_SCHEMA
    spec["arms"] = {
        "control": {
            **structured_profile,
            "profile_id": "structured-direct/v1",
            "treatment_id": "structured-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
        "candidate": {
            **structured_profile,
            "profile_id": "agent-workflow-bm5/v1",
            "treatment_id": "agent-workflow-bm5/v1",
            "runner": {"kind": "agent-workflow", "agent_class": agent_class},
            "enabled_features": [
                *structured_profile.get("enabled_features", []),
                "Agent-Workflow Agent Run lifecycle",
                "compact executor-context projection (OPT-001/004/007)",
                "host-owned deterministic gates (OPT-005)",
                "single agent-finish closeout transaction (OPT-010/011)",
                "host-derived acceptance criteria (OPT-012)",
                "steering-first exceptional worker protocol (OPT-013)",
                "per-command/cache amplification telemetry (OPT-014)",
                "conditional verify/repair model invocation (OPT-015)",
            ],
            "disabled_features": [],
        },
    }
    atomic_write_json(spec_path, spec)
    validate_spec(spec_path)
    result.update(
        study="bm5-structured-direct-vs-agent-workflow-slimmed",
        schema=BENCHMARK_SPEC_V3_SCHEMA,
        agent_class=agent_class,
        model="gpt-6-luna",
        effort="high",
        optimizations=[f"OPT-{index:03d}" for index in range(1, 16)],
    )
    return result


def create_fixture(spec: Path, destination: Path, *, force: bool = False) -> dict[str, Any]:
    return materialize_fixture(spec, destination, force=force)


def create_plan(
    settings: Settings,
    *,
    spec: Path,
    executor: Path,
    repo: Path,
    base_ref: str,
    run_id: str | None,
    repetitions: int | None,
    worktree_root: Path | None,
    allow_dirty: bool,
    assistance_cohort: str | None = None,
    policy: Path | None = None,
    runtime_lock: Path | None = None,
    codebase_memory_mode: str = "none",
) -> dict[str, Any]:
    return create_run_plan(
        settings,
        spec_path=spec,
        executor_path=executor,
        repo=repo,
        base_ref=base_ref,
        run_id=run_id,
        repetitions=repetitions,
        worktree_root=worktree_root,
        allow_dirty=allow_dirty,
        assistance_cohort=assistance_cohort,
        policy_path=policy,
        runtime_lock_path=runtime_lock,
        codebase_memory_mode=codebase_memory_mode,
    )


def _finalize_automated(settings: Settings, plan: Path) -> dict[str, Any]:
    # Publication/visual tooling is optional benchmark machinery. Keep it off
    # validation/readiness/auth paths and load it only for the automated run.
    from .live_review import start_live_review
    from .reporting import write_report
    from .visual import capture_run
    plan_value = read_object(plan)
    run_dir = Path(plan_value["coordinator"]["run_dir"])
    pipeline_started = time.monotonic()

    def timed(field: str, operation: Any) -> Any:
        started = time.monotonic()
        stage = field.removesuffix("_stage_wall_seconds")
        try:
            result = operation(plan)
        except Exception as exc:
            state_value = read_object(run_dir / "run.json")
            state_value.update(
                state="failed",
                failed_stage=stage,
                error=str(exc),
                updated_at=utc_now(),
                **{field: round(time.monotonic() - started, 6)},
            )
            atomic_write_json(run_dir / "run.json", state_value)
            raise
        state_value = read_object(run_dir / "run.json")
        state_value[field] = round(time.monotonic() - started, 6)
        state_value["updated_at"] = utc_now()
        atomic_write_json(run_dir / "run.json", state_value)
        return result

    timed("execution_stage_wall_seconds", lambda path: execute_run(path, settings=settings))
    timed("execution_seal_stage_wall_seconds", seal_execution)
    live_review = timed("live_review_stage_wall_seconds", start_live_review)
    timed("visual_capture_stage_wall_seconds", capture_run)
    timed("machine_scoring_stage_wall_seconds", score_run)
    consolidated = timed("consolidation_stage_wall_seconds", consolidate_run)
    report_started = time.monotonic()
    report = write_report(plan)
    report_wall = round(time.monotonic() - report_started, 6)
    state = read_object(run_dir / "run.json")
    state.update(
        state="awaiting_human_review"
        if report["state"] == "awaiting_human_review"
        else "completed",
        updated_at=utc_now(),
        automated_pipeline_completed_at=utc_now(),
        reporting_stage_wall_seconds=report_wall,
        automated_pipeline_wall_seconds=round(time.monotonic() - pipeline_started, 6),
    )
    atomic_write_json(run_dir / "run.json", state)
    # Regenerate after terminal stage timings are durable so the report exposes
    # end-to-end wall time rather than only the pre-report snapshot.
    report = write_report(plan)
    write_manifest(run_dir)
    return {
        "run_id": plan_value["run_id"],
        "state": state["state"],
        "run_dir": str(run_dir),
        "report": str(run_dir / "report.json"),
        "markdown": str(run_dir / "report.md"),
        "consolidation": consolidated,
        "live_review": live_review,
        "automated_pipeline_wall_seconds": state["automated_pipeline_wall_seconds"],
    }


def _existing_automated_result(plan_path: Path) -> dict[str, Any] | None:
    from .live_review import live_review_status
    plan = read_object(plan_path)
    run_dir = Path(plan["coordinator"]["run_dir"])
    required = (
        run_dir / "visual-capture-summary.json",
        run_dir / "machine-scores.json",
        run_dir / "consolidation-receipt.json",
        run_dir / "report.json",
        run_dir / "report.md",
    )
    if not all(path.is_file() for path in required):
        return None
    verification = verify_consolidated_run(run_dir)
    if not verification["valid"]:
        return None
    live = live_review_status(plan_path)
    if live["total"] == 0 or live["ready"] != live["total"]:
        return None
    state = read_object(run_dir / "run.json")
    return {
        "run_id": plan["run_id"],
        "state": state["state"],
        "run_dir": str(run_dir),
        "report": str(run_dir / "report.json"),
        "markdown": str(run_dir / "report.md"),
        "consolidation": {
            "receipt": str(run_dir / "consolidation-receipt.json"),
            "manifest": str(run_dir / "MANIFEST.sha256"),
            "existing": True,
        },
        "automated_pipeline_wall_seconds": state.get("automated_pipeline_wall_seconds"),
        "live_review": live,
        "existing": True,
    }


def run_benchmark(
    settings: Settings,
    run: str | Path,
    *,
    execution_only: bool = False,
) -> dict[str, Any]:
    plan = _resolve_plan(settings, run)
    if execution_only:
        state = execute_run(plan, settings=settings)
        plan_value = read_object(plan)
        return {
            **state,
            "run_id": plan_value["run_id"],
            "run_dir": str(Path(plan_value["coordinator"]["run_dir"])),
            "execution_only": True,
            "execution_complete": state.get("state") == "executed",
            "execution_sealed": False,
            "benchmark_complete": False,
            "score_eligible": False,
            "pending_stages": [
                "execution-seal",
                "visual-capture",
                "machine-scoring",
                "consolidation",
                "human-review/report",
            ],
            "report": None,
        }
    return _existing_automated_result(plan) or _finalize_automated(settings, plan)


def resume_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    plan = _resolve_plan(settings, run)
    return _existing_automated_result(plan) or _finalize_automated(settings, plan)



def start_live_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    from .live_review import start_live_review
    return start_live_review(_resolve_plan(settings, run))


def stop_live_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    from .live_review import stop_live_review
    return stop_live_review(_resolve_plan(settings, run))


def visual_capture_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    from .visual import capture_run
    return capture_run(_resolve_plan(settings, run))


def seal_benchmark_execution(settings: Settings, run: str | Path) -> dict[str, Any]:
    return seal_execution(_resolve_plan(settings, run))


def verify_benchmark_execution_seal(settings: Settings, run: str | Path) -> dict[str, Any]:
    return verify_execution_seal(_resolve_plan(settings, run))


def score_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    return score_run(_resolve_plan(settings, run))


def consolidate_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    return consolidate_run(_resolve_plan(settings, run))


def prepare_or_submit_review(
    settings: Settings,
    run: str | Path,
    *,
    reviewer: str,
    input_path: Path | None,
) -> dict[str, Any]:
    from .reporting import write_report
    from .review import prepare_assignment, submit_review

    plan = _resolve_plan(settings, run)
    result = submit_review(plan, reviewer, input_path) if input_path else prepare_assignment(plan, reviewer)
    if input_path:
        report = write_report(plan)
        plan_value = read_object(plan)
        run_dir = Path(plan_value["coordinator"]["run_dir"])
        state = read_object(run_dir / "run.json")
        state.update(
            state="completed" if report["state"] not in {"awaiting_human_review", "descriptive_only"} else "awaiting_human_review",
            updated_at=utc_now(),
        )
        atomic_write_json(run_dir / "run.json", state)
        write_manifest(run_dir)
        result["report_state"] = report["state"]
    return result


def render_benchmark_report(settings: Settings, run: str | Path) -> dict[str, Any]:
    from .reporting import write_report
    return write_report(_resolve_plan(settings, run))


def verify_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    plan = read_object(_resolve_plan(settings, run))
    return verify_consolidated_run(Path(plan["coordinator"]["run_dir"]))



def cleanup_benchmark(
    settings: Settings,
    run: str | Path,
    *,
    remove_worktrees: bool = False,
    stop_live_apps: bool = False,
) -> dict[str, Any]:
    from .live_review import live_review_status, stop_live_review

    plan_path = _resolve_plan(settings, run)
    plan = read_object(plan_path)
    run_dir = Path(plan["coordinator"]["run_dir"])
    verification = verify_consolidated_run(run_dir)
    if remove_worktrees and not verification["valid"]:
        raise WorkflowError("benchmark evidence must verify before arm worktrees are removed")
    live_cleanup = stop_live_review(plan_path) if stop_live_apps else live_review_status(plan_path)
    remaining_live = int(
        live_cleanup.get("remaining", live_cleanup.get("ready", 0))
    )
    if remove_worktrees and remaining_live:
        raise WorkflowError(
            "benchmark live applications remain active; worktrees were preserved"
        )
    repository = Path(plan["source"]["repository"])
    removed: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    for pair in plan["pairs"]:
        for attempt in attempts_for(pair):
            for arm_name in ("control_raw", "workflow_full"):
                arm = attempt["arms"][arm_name]
                worktree = Path(arm["worktree"])
                if not remove_worktrees:
                    preserved.append({
                        "pair_id": pair["pair_id"], "attempt": attempt["attempt"], "arm": arm_name,
                        "worktree": str(worktree), "worktree_present": worktree.is_dir(),
                        "branch": arm["branch"],
                    })
                    continue
                result = run_process(
                    ["git", "-C", str(repository), "worktree", "remove", "--force", str(worktree)],
                    check=False,
                    environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
                )
                if result.returncode not in {0, 128}:
                    raise WorkflowError(str(result.stderr).strip() or f"failed to remove benchmark worktree {worktree}")
                branch_result = run_process(
                    ["git", "-C", str(repository), "branch", "-D", str(arm["branch"])],
                    check=False,
                    environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
                )
                removed.append({
                    "pair_id": pair["pair_id"], "attempt": attempt["attempt"], "arm": arm_name,
                    "worktree": str(worktree), "worktree_removed": not worktree.exists(),
                    "branch": arm["branch"], "branch_delete_returncode": branch_result.returncode,
                })
    cleanup_value = {
        "schema": "agent-workflow/benchmark-cleanup/v1", "run_id": plan["run_id"],
        "completed_at": utc_now(), "verification": verification, "removed": removed,
        "preserved": preserved, "remove_worktrees": remove_worktrees,
        "stop_live_apps": stop_live_apps, "live_review": live_cleanup,
        "coordinator_preserved": plan["coordinator"]["worktree"],
    }
    atomic_write_json(run_dir / "cleanup.json", cleanup_value)
    write_manifest(run_dir)
    return cleanup_value



def benchmark_readiness(
    spec: Path,
    executor: Path,
    *,
    policy: Path | None = None,
    runtime_lock: Path | None = None,
    settings: Settings | None = None,
    execution_only: bool = False,
) -> dict[str, Any]:
    """Evaluate whether a benchmark profile can be planned without creating worktrees."""
    base_spec = validate_spec(spec)
    configured = validate_executor_config(executor)
    operating_policy = (
        load_operating_policy(policy)
        if policy is not None
        else implicit_operating_policy(base_spec)
    )
    effective_spec = apply_operating_policy(
        base_spec,
        operating_policy,
        authentication_mode=str(configured["authentication"]["mode"]),
    )
    lock_path = (
        runtime_lock.expanduser().resolve()
        if runtime_lock is not None
        else (spec.expanduser().resolve().parent / str(base_spec["visual"]["runtime_lock_path"])).resolve()
    )
    checks: list[dict[str, Any]] = []
    authentication = preflight_authentication(configured)
    checks.append({
        "id": "authentication",
        "passed": bool(authentication["authenticated"]),
        "detail": authentication["detail"],
    })
    benchmark_runtime_passed = False
    try:
        lock_value = read_object(lock_path)
        validate_runtime_lock(lock_value, claim_level=str(effective_spec["claim_level"]))
        if execution_only:
            runtime = {
                "runtime_state": "not-required",
                "detail": "visual attestation is not required for execution-only smoke runs",
            }
            checks.append({
                "id": "visual-runtime",
                "passed": True,
                "detail": "not required for execution-only run; runtime-lock structure is valid",
            })
        else:
            runtime = attest_runtime(lock_path, claim_level=str(effective_spec["claim_level"]))
            required_state = (
                "publication-verified"
                if effective_spec["claim_level"] == "publication"
                else "development-verified"
            )
            runtime_passed = runtime["runtime_state"] in (
                {"publication-verified"}
                if required_state == "publication-verified"
                else {"development-verified", "publication-verified"}
            )
            benchmark_runtime_passed = runtime_passed
            checks.append({
                "id": "visual-runtime",
                "passed": runtime_passed,
                "detail": f"required={required_state}; observed={runtime['runtime_state']}",
            })
    except WorkflowError as exc:
        runtime = {"runtime_state": "not-verified", "detail": str(exc)}
        checks.append({"id": "visual-runtime", "passed": False, "detail": str(exc)})
    checks.extend([
        {
            "id": "headless-executor",
            "passed": (
                bool(configured.get("argv_template"))
                and (
                    shutil.which(str(configured["argv_template"][0])) is not None
                    or Path(str(configured["argv_template"][0])).exists()
                )
            ),
            "detail": (
                f"executor={configured['executor']}; "
                f"binary={configured['argv_template'][0] if configured.get('argv_template') else 'missing'}; "
                "benchmark arms execute without a terminal host"
            ),
        },
        {
            "id": "paired-repetitions",
            "passed": int(operating_policy["repetitions"]) >= int(operating_policy["winner_policy"]["minimum_eligible_pairs"])
            if operating_policy["winner_policy"]["enabled"]
            else True,
            "detail": (
                f"repetitions={operating_policy['repetitions']}; "
                f"minimum={operating_policy['winner_policy']['minimum_eligible_pairs']}"
            ),
        },
        {
            "id": "subscription-default",
            "passed": operating_policy["authentication_default"] == "subscription-session",
            "detail": f"default={operating_policy['authentication_default']}; selected={configured['authentication']['mode']}",
        },
        {
            "id": "retry-isolation",
            "passed": bool(operating_policy["retry_policy"]["fresh_pair_worktrees"]),
            "detail": (
                f"retries={operating_policy['infrastructure_retries']}; "
                f"classification={operating_policy['retry_policy']['classification']}"
            ),
        },
    ])
    if effective_spec.get("schema") == BENCHMARK_SPEC_V3_SCHEMA and uses_agent_workflow(effective_spec):
        if settings is None:
            checks.append({
                "id": "agent-workflow-settings",
                "passed": False,
                "detail": "benchmark v3 Agent-Workflow treatment readiness requires host Settings",
            })
        else:
            checks.extend(treatment_runtime_checks(settings, effective_spec, configured))
    execution_ready = all(item["passed"] for item in checks)
    full_pipeline_ready = execution_ready and benchmark_runtime_passed
    return {
        "benchmark_id": effective_spec["benchmark_id"],
        "claim_level": effective_spec["claim_level"],
        "policy_id": operating_policy["policy_id"],
        "executor": {
            "provider": configured["provider"],
            "executor": configured["executor"],
            "model": configured["model"],
            "authentication_mode": configured["authentication"]["mode"],
            "billing_mode": configured["billing"]["mode"],
        },
        "authentication": authentication,
        "runtime": runtime,
        "checks": checks,
        "execution_only": execution_only,
        "execution_ready": execution_ready,
        "full_pipeline_ready": full_pipeline_ready,
        "benchmark_completion_requires": [
            "verified visual runtime",
            "visual capture for every selected arm",
            "machine scoring",
            "consolidated evidence",
            "required human review before composite/winner claims",
        ],
        "ready": execution_ready if execution_only else full_pipeline_ready,
    }

def check_benchmark_auth(executor: Path) -> dict[str, Any]:
    configured = validate_executor_config(executor)
    return preflight_authentication(configured)


def attest_benchmark_runtime(runtime_lock: Path, *, claim_level: str = "development") -> dict[str, Any]:
    return attest_runtime(runtime_lock, claim_level=claim_level)


def seal_benchmark_runtime(base_lock: Path, output: Path, *, container_image: str) -> dict[str, Any]:
    return seal_runtime_lock(base_lock, output, container_image=container_image)


def status_benchmark(settings: Settings, run: str | Path) -> dict[str, Any]:
    from .live_review import live_review_status
    plan = read_object(_resolve_plan(settings, run))
    run_dir = Path(plan["coordinator"]["run_dir"])
    state = read_object(run_dir / "run.json")
    reviews = list((run_dir / "human-review" / "reviews").glob("*.json")) if (run_dir / "human-review" / "reviews").is_dir() else []
    live = live_review_status(_resolve_plan(settings, run))
    visual_capture = (run_dir / "visual-capture-summary.json").is_file()
    execution_seal_path = run_dir / "execution-seal.json"
    execution_sealed = execution_seal_path.is_file()
    machine_scores = (run_dir / "machine-scores.json").is_file()
    consolidated = (run_dir / "consolidation-receipt.json").is_file()
    report_path = run_dir / "report.json"
    execution_complete = state.get("state") in {"executed", "awaiting_human_review", "completed"}
    benchmark_complete = bool(
        execution_complete and visual_capture and machine_scores and consolidated and report_path.is_file()
    )
    return {
        **state,
        "run_dir": str(run_dir),
        "live_review": live,
        "run_plan": str(run_dir / "run-plan.json"),
        "execution_complete": execution_complete,
        "execution_sealed": execution_sealed,
        "execution_seal": str(execution_seal_path) if execution_sealed else None,
        "benchmark_complete": benchmark_complete,
        "visual_capture": visual_capture,
        "machine_scores": machine_scores,
        "consolidated": consolidated,
        "human_reviews": len(reviews),
        "report": str(report_path) if report_path.is_file() else None,
    }
