from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file, utc_now

from .common import canonical_json_sha256, file_inventory, read_object, tree_sha256

EXECUTION_SEAL_SCHEMA = "agent-workflow/benchmark-execution-seal/v1"
_POST_EXECUTION_STAGE_PATHS = (
    "scores",
    "visual",
    "score.json",
    "product-score.json",
)


def _run_dir(plan: Mapping[str, Any]) -> Path:
    return Path(str(plan["coordinator"]["run_dir"]))


def _execution_stage_inventory(stage: Path) -> list[dict[str, Any]]:
    return file_inventory(stage, exclude=_POST_EXECUTION_STAGE_PATHS)


def _worktree_sha256(worktree: Path) -> str:
    return tree_sha256(
        worktree,
        exclude=(".git", ".agent-workflow-benchmark"),
    )


def _seal_payload(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path)
    run_dir = _run_dir(plan)
    state_path = run_dir / "run.json"
    if not state_path.is_file():
        raise WorkflowError(f"benchmark run state is missing: {state_path}")
    state = read_object(state_path)
    if state.get("state") != "executed":
        raise WorkflowError(
            "benchmark execution must be complete before sealing; "
            f"observed state={state.get('state')!r}"
        )
    if (run_dir / "machine-scores.json").exists():
        raise WorkflowError(
            "benchmark execution must be sealed before machine scoring"
        )

    arms: list[dict[str, Any]] = []
    for pair in plan.get("pairs", []):
        for attempt in pair.get("attempts", []):
            for arm_name in ("control_raw", "workflow_full"):
                arm = attempt["arms"][arm_name]
                worktree = Path(str(arm["worktree"]))
                stage = Path(str(arm["stage_dir"]))
                if not worktree.is_dir():
                    raise WorkflowError(
                        f"benchmark arm worktree is missing before seal: {worktree}"
                    )
                if not (stage / "arm.json").is_file():
                    raise WorkflowError(
                        f"benchmark arm execution evidence is incomplete: {stage / 'arm.json'}"
                    )
                arms.append(
                    {
                        "pair_id": str(pair["pair_id"]),
                        "case_id": str(pair["case_id"]),
                        "repetition": int(pair["repetition"]),
                        "attempt": int(attempt["attempt"]),
                        "arm": arm_name,
                        "worktree": str(worktree),
                        "worktree_tree_sha256": _worktree_sha256(worktree),
                        "execution_stage": str(stage),
                        "execution_stage_inventory": _execution_stage_inventory(stage),
                    }
                )

    payload: dict[str, Any] = {
        "schema": EXECUTION_SEAL_SCHEMA,
        "run_id": str(plan["run_id"]),
        "benchmark_id": str(plan["benchmark_id"]),
        "sealed_at": utc_now(),
        "run_plan_path": str(plan_path),
        "run_plan_sha256": sha256_file(plan_path),
        "execution_state": "executed",
        "arms": arms,
    }
    payload["seal_sha256"] = canonical_json_sha256(payload)
    return payload


def seal_execution(plan_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    plan = read_object(plan_path)
    path = _run_dir(plan) / "execution-seal.json"
    if path.is_file():
        verification = verify_execution_seal(plan_path)
        if not verification["valid"]:
            raise WorkflowError(
                "existing benchmark execution seal no longer verifies: "
                + "; ".join(verification["mismatches"])
            )
        return read_object(path)
    payload = _seal_payload(plan_path)
    atomic_write_json(path, payload)
    return payload


def verify_execution_seal(plan_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    plan = read_object(plan_path)
    run_dir = _run_dir(plan)
    path = run_dir / "execution-seal.json"
    if not path.is_file():
        return {
            "schema": EXECUTION_SEAL_SCHEMA,
            "run_id": str(plan["run_id"]),
            "valid": False,
            "sealed": False,
            "mismatches": ["execution seal is missing"],
            "seal": str(path),
        }

    seal = read_object(path)
    mismatches: list[str] = []
    if seal.get("schema") != EXECUTION_SEAL_SCHEMA:
        mismatches.append(f"unexpected execution seal schema: {seal.get('schema')!r}")
    if seal.get("run_id") != plan.get("run_id"):
        mismatches.append("execution seal run_id does not match run plan")
    if seal.get("benchmark_id") != plan.get("benchmark_id"):
        mismatches.append("execution seal benchmark_id does not match run plan")
    if seal.get("run_plan_sha256") != sha256_file(plan_path):
        mismatches.append("run plan changed after execution seal")

    seal_copy = dict(seal)
    observed_seal_sha = seal_copy.pop("seal_sha256", None)
    expected_seal_sha = canonical_json_sha256(seal_copy)
    if observed_seal_sha != expected_seal_sha:
        mismatches.append("execution seal receipt hash is invalid")

    for item in seal.get("arms", []):
        label = (
            f"{item.get('pair_id')} attempt={item.get('attempt')} "
            f"arm={item.get('arm')}"
        )
        worktree = Path(str(item.get("worktree", "")))
        if not worktree.is_dir():
            mismatches.append(f"{label}: worktree is missing")
        else:
            observed = _worktree_sha256(worktree)
            if observed != item.get("worktree_tree_sha256"):
                mismatches.append(f"{label}: worktree changed after seal")

        stage = Path(str(item.get("execution_stage", "")))
        if not stage.is_dir():
            mismatches.append(f"{label}: execution stage is missing")
        else:
            observed_inventory = _execution_stage_inventory(stage)
            if observed_inventory != item.get("execution_stage_inventory"):
                mismatches.append(f"{label}: execution evidence changed after seal")

    return {
        "schema": EXECUTION_SEAL_SCHEMA,
        "run_id": str(plan["run_id"]),
        "valid": not mismatches,
        "sealed": True,
        "mismatches": mismatches,
        "seal": str(path),
        "seal_sha256": seal.get("seal_sha256"),
    }


def require_execution_seal(plan_path: Path) -> dict[str, Any]:
    result = verify_execution_seal(plan_path)
    if not result["valid"]:
        raise WorkflowError(
            "benchmark scoring requires a valid execution seal: "
            + "; ".join(result["mismatches"])
        )
    return result
