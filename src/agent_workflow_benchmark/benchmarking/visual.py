from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import atomic_write_json, sha256_file, utc_now
from .common import child, file_inventory, format_argv, read_object
from .contracts import BENCHMARK_VISUAL_EVIDENCE_SCHEMA, validate_spec, validate_value
from .events import append_event
from .pairing import selected_arms
from .runtime import attest_runtime
from .live_review import live_url_for


def _capture_arm(
    plan: Mapping[str, Any], pair: Mapping[str, Any], pair_state: Mapping[str, Any],
    arm: Mapping[str, Any], spec: Mapping[str, Any],
) -> dict[str, Any]:
    stage = Path(arm["stage_dir"])
    visual_dir = stage / "visual"
    visual_dir.mkdir(parents=True, exist_ok=True)
    suite = Path(plan["coordinator"]["suite_dir"])
    runtime_lock = child(suite, spec["visual"]["runtime_lock_path"], "visual runtime lock")
    live_url = live_url_for(plan, str(pair["pair_id"]), str(arm["arm"]))
    values = {
        "run_id": str(plan["run_id"]), "pair_id": str(pair["pair_id"]),
        "case_id": str(pair["case_id"]), "arm": str(arm["arm"]),
        "worktree": str(arm["worktree"]), "stage_dir": str(stage),
        "visual_dir": str(visual_dir), "suite": str(suite), "runtime_lock": str(runtime_lock),
        "live_url": live_url or "unavailable",
    }
    if any("{live_url}" in str(item) for item in spec["visual"]["capture_argv"]) and not live_url:
        raise WorkflowError(f"live review application is not ready for {pair['pair_id']} {arm['arm']}")
    argv = format_argv(spec["visual"]["capture_argv"], values)
    started = utc_now()
    result = run(
        argv, cwd=Path(arm["worktree"]), check=False,
        timeout_seconds=float(spec["visual"]["timeout_seconds"]),
        max_stdout_bytes=4 * 1024 * 1024, max_stderr_bytes=4 * 1024 * 1024,
        environment=EnvironmentPolicy(
            allowlist=tuple(plan["executor"].get("environment_allowlist", [])),
            values={
                "AGENT_WORKFLOW_BENCHMARK_RUN_ID": str(plan["run_id"]),
                "AGENT_WORKFLOW_BENCHMARK_PAIR_ID": str(pair["pair_id"]),
                "AGENT_WORKFLOW_BENCHMARK_ARM": str(arm["arm"]),
                "AGENT_WORKFLOW_BENCHMARK_VISUAL_DIR": str(visual_dir),
                "AGENT_WORKFLOW_BENCHMARK_RUNTIME_LOCK": str(runtime_lock),
            },
            unsafe_inherit=bool(plan["executor"].get("unsafe_inherit_environment", False)),
        ),
        probe_version=True, digest_executable=True,
    )
    (visual_dir / "capture.stdout.log").write_text(str(result.stdout), encoding="utf-8")
    (visual_dir / "capture.stderr.log").write_text(str(result.stderr), encoding="utf-8")
    assessment = visual_dir / "assessment.json"
    assessment_value = read_object(assessment) if assessment.is_file() else {}
    attestation = attest_runtime(runtime_lock, claim_level=str(plan["claim_level"]))
    actual_browser = assessment_value.get("runtime", {}).get("browser_version")
    locked_browser = assessment_value.get("runtime_lock", {}).get("browser_version")
    browser_version_matches = bool(actual_browser and locked_browser and actual_browser == locked_browser)
    attestation["actual_browser_version"] = actual_browser
    attestation["checks"]["browser_version"] = browser_version_matches
    if not browser_version_matches:
        attestation["runtime_state"] = "not-verified"
    elif plan["claim_level"] == "publication" and attestation["runtime_state"] != "publication-verified":
        attestation["runtime_state"] = "not-verified"
    capture_complete = assessment_value.get("capture_state") == "complete" and result.returncode == 0
    evidence = {
        "schema": BENCHMARK_VISUAL_EVIDENCE_SCHEMA, "run_id": plan["run_id"],
        "pair_id": pair["pair_id"], "arm": arm["arm"],
        "attempt": int(pair_state.get("selected_attempt", 1)), "claim_level": plan["claim_level"],
        "runtime_lock_sha256": sha256_file(runtime_lock), "runtime_attestation": attestation,
        "runtime_state": attestation["runtime_state"],
        "assessment_sha256": sha256_file(assessment) if assessment.is_file() else "0" * 64,
        "artifacts": [item for item in file_inventory(visual_dir) if item["path"] not in {"capture.json", "visual-evidence.json"}],
        "captured_at": utc_now(),
    }
    validate_value(evidence, BENCHMARK_VISUAL_EVIDENCE_SCHEMA, f"visual evidence {pair['pair_id']} {arm['arm']}")
    atomic_write_json(visual_dir / "visual-evidence.json", evidence)
    state = "complete" if capture_complete and attestation["runtime_state"] != "not-verified" else "harness_failure"
    value = {
        "state": state, "started_at": started, "completed_at": utc_now(),
        "duration_seconds": result.duration_seconds, "returncode": result.returncode,
        "error_category": result.error_category, "runtime_lock": str(runtime_lock),
        "runtime_lock_sha256": sha256_file(runtime_lock),
        "runtime_state": attestation["runtime_state"],
        "runtime_attestation": str(visual_dir / "visual-evidence.json"),
        "assessment": str(assessment) if assessment.is_file() else None,
        "live_url": live_url,
        "assessment_sha256": sha256_file(assessment) if assessment.is_file() else None,
        "stdout": str(visual_dir / "capture.stdout.log"), "stderr": str(visual_dir / "capture.stderr.log"),
    }
    atomic_write_json(visual_dir / "capture.json", value)
    return value


def capture_run(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    summary_path = run_dir / "visual-capture-summary.json"
    if summary_path.is_file():
        return read_object(summary_path)
    spec = validate_spec(Path(plan["coordinator"]["spec_path"]))
    results: list[dict[str, Any]] = []
    append_event(run_dir, event_type="visual_capture_started", run_id=str(plan["run_id"]))
    for pair in plan["pairs"]:
        pair_state_path = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / "pair.json"
        pair_state = read_object(pair_state_path)
        arms = selected_arms(pair, pair_state)
        for arm_name in ("control_raw", "workflow_full"):
            arm = arms[arm_name]
            existing = Path(arm["stage_dir"]) / "visual" / "capture.json"
            capture = read_object(existing) if existing.is_file() else _capture_arm(plan, pair, pair_state, arm, spec)
            results.append({"pair_id": pair["pair_id"], "arm": arm_name, "attempt": pair_state["selected_attempt"], **capture})
    summary = {
        "run_id": plan["run_id"], "captures": results,
        "complete": sum(1 for item in results if item["state"] == "complete"),
        "harness_failures": sum(1 for item in results if item["state"] != "complete"),
        "publication_verified": sum(1 for item in results if item.get("runtime_state") == "publication-verified"),
    }
    atomic_write_json(summary_path, summary)
    append_event(run_dir, event_type="visual_capture_terminal", run_id=str(plan["run_id"]), payload={"complete": summary["complete"], "harness_failures": summary["harness_failures"]})
    return summary
