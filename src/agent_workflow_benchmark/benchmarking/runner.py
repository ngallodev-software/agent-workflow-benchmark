from __future__ import annotations

import concurrent.futures
import hashlib
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import atomic_write_json, sha256_file, utc_now
from .common import format_argv, read_object
from .contracts import BENCHMARK_ARM_SCHEMA, BENCHMARK_PAIR_SCHEMA, validate_value
from .events import append_event
from .metrics import aggregate_usage, load_usage
from .pairing import attempts_for

TERMINAL_PHASE_STATES = {"completed", "task_failed", "infrastructure_failed", "timed_out"}


def _prompt_for(arm: Mapping[str, Any], phase_id: str) -> Path:
    for item in arm["prompts"]:
        if item["phase_id"] == phase_id:
            return Path(item["path"])
    raise WorkflowError(f"arm has no prompt for phase {phase_id}")


def _render_command(
    plan: Mapping[str, Any], pair: Mapping[str, Any], attempt: Mapping[str, Any],
    arm: Mapping[str, Any], phase: Mapping[str, Any],
) -> tuple[list[str], dict[str, str], Path, str | None]:
    worktree = Path(arm["worktree"])
    stage = Path(arm["stage_dir"])
    prompt_file = _prompt_for(arm, str(phase["id"]))
    phase_dir = stage / "phases" / str(phase["id"])
    phase_dir.mkdir(parents=True, exist_ok=True)
    usage_file = phase_dir / "usage.json"
    values = {
        "run_id": str(plan["run_id"]), "benchmark_id": str(plan["benchmark_id"]),
        "pair_id": str(pair["pair_id"]), "case_id": str(pair["case_id"]),
        "repetition": str(pair["repetition"]), "attempt": str(attempt["attempt"]),
        "attempt_id": str(attempt["attempt_id"]), "pair_nonce": str(attempt["pair_nonce"]),
        "arm": str(arm["arm"]), "slot": str(arm["slot"]), "phase_id": str(phase["id"]),
        "model": str(plan["executor"]["model"]), "effort": str(plan["executor"].get("effort") or ""),
        "worktree": str(worktree), "stage_dir": str(stage), "phase_dir": str(phase_dir),
        "prompt_file": str(prompt_file), "usage_file": str(usage_file),
        "suite": str(plan["coordinator"]["suite_dir"]), "run_dir": str(plan["coordinator"]["run_dir"]),
    }
    argv = format_argv(plan["executor"]["argv_template"], values)
    sandbox = plan["executor"]["sandbox"]
    if sandbox.get("argv_prefix"):
        argv = format_argv(sandbox["argv_prefix"], values) + argv
    environment = {
        "AGENT_WORKFLOW_BENCHMARK_RUN_ID": values["run_id"],
        "AGENT_WORKFLOW_BENCHMARK_PAIR_ID": values["pair_id"],
        "AGENT_WORKFLOW_BENCHMARK_ATTEMPT_ID": values["attempt_id"],
        "AGENT_WORKFLOW_BENCHMARK_CASE_ID": values["case_id"],
        "AGENT_WORKFLOW_BENCHMARK_ARM": values["arm"],
        "AGENT_WORKFLOW_BENCHMARK_SLOT": values["slot"],
        "AGENT_WORKFLOW_BENCHMARK_PHASE": values["phase_id"],
        "AGENT_WORKFLOW_BENCHMARK_PROMPT": values["prompt_file"],
        "AGENT_WORKFLOW_BENCHMARK_USAGE_FILE": values["usage_file"],
        "AGENT_WORKFLOW_BENCHMARK_STAGE_DIR": values["stage_dir"],
        "AGENT_WORKFLOW_BENCHMARK_PAIR_NONCE": values["pair_nonce"],
        "AGENT_WORKFLOW_CODEBASE_MEMORY_MODE": str(plan.get("codebase_memory_mode", "none")),
        **{str(key): str(value) for key, value in plan["executor"].get("environment", {}).items()},
    }
    delivery = plan["executor"]["prompt_delivery"]
    prompt_text: str | None = None
    if delivery["source"] == "stdin-prompt-file":
        prompt_text = prompt_file.read_text(encoding="utf-8")
        if delivery.get("append_newline") and not prompt_text.endswith("\n"):
            prompt_text += "\n"
    return argv, environment, phase_dir, prompt_text


def _run_phase_arm(
    plan: Mapping[str, Any], pair: Mapping[str, Any], attempt: Mapping[str, Any],
    arm: Mapping[str, Any], phase: Mapping[str, Any], barrier: threading.Barrier,
    release: dict[str, float],
) -> dict[str, Any]:
    """Execute one benchmark arm headlessly with bounded process evidence."""
    run_dir = Path(plan["coordinator"]["run_dir"])
    argv, environment, phase_dir, prompt_text = _render_command(plan, pair, attempt, arm, phase)
    stdout_path, stderr_path = phase_dir / "stdout.log", phase_dir / "stderr.log"
    barrier.wait()
    actual_start_monotonic = time.monotonic()
    actual_start_utc = utc_now()
    start_offset = round(actual_start_monotonic - release["monotonic"], 9)
    append_event(
        run_dir, event_type="phase_started", run_id=str(plan["run_id"]),
        pair_id=str(pair["pair_id"]), arm=str(arm["arm"]), phase_id=str(phase["id"]),
        payload={"slot": arm["slot"], "attempt": attempt["attempt"]},
    )
    credential_names = tuple(
        str(name)
        for name in plan["executor"].get("authentication", {}).get("credential_environment", [])
    )
    allowlist = tuple(dict.fromkeys(
        [str(name) for name in plan["executor"].get("environment_allowlist", [])]
        + list(credential_names)
    ))
    result = run(
        argv,
        cwd=Path(str(arm["worktree"])),
        check=False,
        timeout_seconds=float(phase["timeout_seconds"]),
        max_stdout_bytes=int(plan["executor"]["max_stdout_bytes"]),
        max_stderr_bytes=int(plan["executor"]["max_stderr_bytes"]),
        environment=EnvironmentPolicy(allowlist=allowlist, values=environment),
        input_text=prompt_text,
    )
    stdout_path.write_text(str(result.stdout), encoding="utf-8")
    stderr_path.write_text(str(result.stderr), encoding="utf-8")
    wall = round(time.monotonic() - actual_start_monotonic, 6)
    stdout_text = str(result.stdout)
    usage = load_usage(
        phase_dir / "usage.json", stdout_text,
        currency=plan["executor"].get("currency"),
        price_catalog_id=plan["executor"].get("price_catalog_id"),
        billing=plan["executor"].get("billing"), pricing=plan["executor"].get("pricing"),
    )
    if result.timed_out:
        state = "timed_out"
    elif result.returncode == 0:
        state = "completed"
    elif result.error_category in {"not-found", "spawn-error", "cancelled"}:
        state = "infrastructure_failed"
    elif plan["executor"].get("nonzero_classification", "task") == "infrastructure":
        state = "infrastructure_failed"
    else:
        state = "task_failed"
    record = {
        "phase_id": phase["id"], "state": state, "started_at": actual_start_utc,
        "start_offset_seconds": start_offset, "completed_at": utc_now(),
        "phase_wall_seconds": wall, "active_process_seconds": result.duration_seconds,
        "provider_elapsed_seconds": usage["provider_elapsed_seconds"],
        "first_output_latency_seconds": usage["first_output_latency_seconds"],
        "verification_seconds": 0.0, "queue_wait_seconds": 0.0, "human_review_seconds": None,
        "process": result.as_dict(include_output=False), "usage": usage,
        "stdout": str(stdout_path), "stderr": str(stderr_path),
        "usage_file": str(phase_dir / "usage.json") if (phase_dir / "usage.json").is_file() else None,
    }
    atomic_write_json(phase_dir / "phase.json", record)
    append_event(
        run_dir, event_type="phase_terminal", run_id=str(plan["run_id"]),
        pair_id=str(pair["pair_id"]), arm=str(arm["arm"]), phase_id=str(phase["id"]),
        payload={"state": state, "wall_seconds": wall, "returncode": result.returncode, "attempt": attempt["attempt"]},
    )
    return record


def _git_evidence(pair: Mapping[str, Any], arm: Mapping[str, Any]) -> dict[str, Any]:
    worktree, base = Path(arm["worktree"]), str(pair["base_revision"])
    patch = run(["git", "-C", str(worktree), "diff", "--binary", "--full-index", base, "--", ":(exclude).agent-workflow-benchmark"], check=False, max_stdout_bytes=16 * 1024 * 1024)
    status = run(
        ["git", "-C", str(worktree), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False, environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
    )
    stage = Path(arm["stage_dir"])
    patch_path = stage / "patch.diff"
    patch_path.write_text(str(patch.stdout), encoding="utf-8")
    changed: list[str] = []
    for line in str(status.stdout).splitlines():
        relative = line[3:].strip()
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not relative.startswith(".agent-workflow-benchmark/"):
            changed.append(relative)
    evidence = {
        "base_revision": base, "patch_path": str(patch_path), "patch_sha256": sha256_file(patch_path),
        "changed_paths": sorted(set(changed)),
        "status_sha256": hashlib.sha256(str(status.stdout).encode()).hexdigest(),
    }
    atomic_write_json(stage / "git-evidence.json", evidence)
    return evidence


def _scope_violations(changed: list[str], scope: Mapping[str, Any]) -> list[str]:
    paths = set(str(item) for item in scope.get("writable_paths", []))
    trees = tuple(str(item).rstrip("/") + "/" for item in scope.get("writable_trees", []))
    disposable = tuple(str(item).rstrip("/") + "/" for item in scope.get("disposable_trees", []))
    return sorted(relative for relative in changed if relative not in paths and not any(relative.startswith(tree) for tree in (*trees, *disposable)))


def _finalize_arm(
    plan: Mapping[str, Any], pair: Mapping[str, Any], attempt: Mapping[str, Any],
    arm: Mapping[str, Any], phase_records: list[dict[str, Any]],
) -> dict[str, Any]:
    stage = Path(arm["stage_dir"])
    git = _git_evidence(pair, arm)
    usage = aggregate_usage([item["usage"] for item in phase_records], billing=plan["executor"].get("billing"))
    states = {item["state"] for item in phase_records}
    state = "infrastructure_failed" if "infrastructure_failed" in states else "task_failed" if states & {"timed_out", "task_failed"} else "completed"
    value = {
        "schema": BENCHMARK_ARM_SCHEMA, "run_id": plan["run_id"], "benchmark_id": plan["benchmark_id"],
        "pair_id": pair["pair_id"], "case_id": pair["case_id"], "repetition": pair["repetition"],
        "attempt": attempt["attempt"], "attempt_id": attempt["attempt_id"],
        "arm": arm["arm"], "slot": arm["slot"], "state": state,
        "base_revision": pair["base_revision"], "fixture_sha256": pair["fixture_sha256"],
        "task_prompt_sha256": arm["task_prompt_sha256"], "arm_wrapper_sha256": arm["arm_wrapper_sha256"],
        "constraint_profile_id": arm["profile_id"], "constraint_profile_sha256": arm["constraint_profile_sha256"],
        "effective_prompt_sha256": {item["phase_id"]: item["effective_prompt_sha256"] for item in arm["prompts"]},
        "worktree": arm["worktree"], "stage_dir": arm["stage_dir"], "phases": phase_records,
        "usage": usage, "git_evidence": git,
        "scope_violations": _scope_violations(git["changed_paths"], pair["allowed_scope"]),
        "assistance": "none" if plan["policies"]["human_assistance"] == "unassisted" else "declared",
        "completed_at": utc_now(),
    }
    validate_value(value, BENCHMARK_ARM_SCHEMA, f"benchmark arm {arm['arm']}")
    atomic_write_json(stage / "arm.json", value)
    atomic_write_json(stage / "phases.json", {"phases": phase_records})
    atomic_write_json(stage / "metrics.json", {"usage": usage})
    return value


def _execute_attempt(plan: Mapping[str, Any], pair: Mapping[str, Any], attempt: Mapping[str, Any]) -> dict[str, Any]:
    run_dir = Path(plan["coordinator"]["run_dir"])
    started = time.monotonic()
    records: dict[str, list[dict[str, Any]]] = {"control_raw": [], "workflow_full": []}
    start_skews: list[float] = []
    infrastructure_failure = False
    for phase in plan["phases"]:
        if infrastructure_failure:
            break
        release: dict[str, float] = {}
        barrier = threading.Barrier(2, action=lambda: release.__setitem__("monotonic", time.monotonic()))
        starts: dict[str, float] = {}
        def invoke(arm_name: str) -> dict[str, Any]:
            result = _run_phase_arm(plan, pair, attempt, attempt["arms"][arm_name], phase, barrier, release)
            starts[arm_name] = float(result["start_offset_seconds"])
            return result
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {name: pool.submit(invoke, name) for name in ("control_raw", "workflow_full")}
            for name, future in futures.items():
                record = future.result()
                records[name].append(record)
                infrastructure_failure = infrastructure_failure or record["state"] == "infrastructure_failed"
        if len(starts) == 2:
            start_skews.append(abs(starts["control_raw"] - starts["workflow_full"]))
    arm_values = {name: _finalize_arm(plan, pair, attempt, attempt["arms"][name], records[name]) for name in ("control_raw", "workflow_full")}
    arm_walls = {name: round(sum(item["phase_wall_seconds"] for item in values), 6) for name, values in records.items()}
    state = "infrastructure_failed" if infrastructure_failure else "terminal"
    attempt_dir = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / f"attempt-{int(attempt['attempt']):02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    value = {
        "attempt": attempt["attempt"], "attempt_id": attempt["attempt_id"], "state": state,
        "pair_nonce_sha256": hashlib.sha256(str(attempt["pair_nonce"]).encode()).hexdigest(),
        "pair_wall_seconds": round(time.monotonic() - started, 6),
        "pair_start_skew_seconds": round(max(start_skews, default=0.0), 6),
        "pair_sum_arm_wall_seconds": round(sum(arm_walls.values()), 6),
        "pair_critical_path_seconds": round(max(arm_walls.values(), default=0.0), 6),
        "arms": {name: str(Path(value["stage_dir"]) / "arm.json") for name, value in arm_values.items()},
        "completed_at": utc_now(),
    }
    atomic_write_json(attempt_dir / "attempt.json", value)
    return {**value, "evidence": str(attempt_dir / "attempt.json")}


def execute_pair(plan: Mapping[str, Any], pair: Mapping[str, Any]) -> dict[str, Any]:
    run_dir = Path(plan["coordinator"]["run_dir"])
    pair_started = time.monotonic()
    append_event(run_dir, event_type="pair_started", run_id=str(plan["run_id"]), pair_id=str(pair["pair_id"]))
    attempt_results: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for attempt in attempts_for(pair):
        result = _execute_attempt(plan, pair, attempt)
        attempt_results.append(result)
        selected = result
        if result["state"] != "infrastructure_failed":
            break
        append_event(run_dir, event_type="pair_retry", run_id=str(plan["run_id"]), pair_id=str(pair["pair_id"]), payload={"attempt": attempt["attempt"]})
    assert selected is not None
    pair_state = "infrastructure_failed" if selected["state"] == "infrastructure_failed" else "terminal"
    evidence = [{"attempt": item["attempt"], "attempt_id": item["attempt_id"], "state": item["state"], "evidence": item["evidence"]} for item in attempt_results]
    value = {
        "schema": BENCHMARK_PAIR_SCHEMA, "run_id": plan["run_id"], "benchmark_id": plan["benchmark_id"],
        "pair_id": pair["pair_id"], "case_id": pair["case_id"], "repetition": pair["repetition"],
        "state": pair_state, "base_revision": pair["base_revision"], "fixture_sha256": pair["fixture_sha256"],
        "task_prompt_sha256": pair["task_prompt_sha256"], "input_bundle_sha256": pair["input_bundle_sha256"],
        "environment_sha256": pair["environment_sha256"], "tool_policy_sha256": pair["tool_policy_sha256"],
        "resource_policy_sha256": pair["resource_policy_sha256"], "pair_nonce_sha256": selected["pair_nonce_sha256"],
        "pair_wall_seconds": round(time.monotonic() - pair_started, 6),
        "pair_start_skew_seconds": selected["pair_start_skew_seconds"],
        "pair_sum_arm_wall_seconds": selected["pair_sum_arm_wall_seconds"],
        "pair_critical_path_seconds": selected["pair_critical_path_seconds"],
        "selected_attempt": selected["attempt"], "infrastructure_retry_count": max(0, len(attempt_results) - 1),
        "attempts": evidence, "arms": selected["arms"], "completed_at": utc_now(),
    }
    validate_value(value, BENCHMARK_PAIR_SCHEMA, f"benchmark pair {pair['pair_id']}")
    pair_state_dir = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}"
    pair_state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pair_state_dir / "pair.json", value)
    append_event(run_dir, event_type="pair_terminal", run_id=str(plan["run_id"]), pair_id=str(pair["pair_id"]), payload={"state": pair_state, "wall_seconds": value["pair_wall_seconds"], "selected_attempt": selected["attempt"]})
    return value


def execute_run(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    state_path = run_dir / "run.json"
    state = read_object(state_path)
    if state["state"] in {"executed", "awaiting_human_review", "completed"}:
        return state
    state.update(
        state="running",
        started_at=state.get("started_at") or utc_now(),
        updated_at=utc_now(),
    )
    atomic_write_json(state_path, state)
    append_event(run_dir, event_type="run_started", run_id=str(plan["run_id"]))
    started = time.monotonic()
    pair_results: list[dict[str, Any]] = []
    try:
        for pair in plan["pairs"]:
            existing = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / "pair.json"
            pair_results.append(read_object(existing) if existing.is_file() else execute_pair(plan, pair))
            state["pairs_terminal"] = len(pair_results)
            state["updated_at"] = utc_now()
            atomic_write_json(state_path, state)
        state.update(state="executed", updated_at=utc_now(), executed_at=utc_now(), benchmark_execution_wall_seconds=round(time.monotonic() - started, 6), pairs_terminal=len(pair_results))
        atomic_write_json(state_path, state)
        append_event(run_dir, event_type="run_executed", run_id=str(plan["run_id"]), payload={"pairs": len(pair_results)})
        return state
    except Exception as exc:
        state.update(state="failed", updated_at=utc_now(), error=str(exc))
        atomic_write_json(state_path, state)
        append_event(run_dir, event_type="run_failed", run_id=str(plan["run_id"]), payload={"error": str(exc)})
        raise
