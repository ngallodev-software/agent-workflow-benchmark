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


def _pair_receipts(run_dir: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted((run_dir / "ps").glob("*/pair.json")):
        value = read_object(path)
        pair_id = str(value.get("pair_id") or "")
        if not pair_id:
            raise WorkflowError(f"benchmark pair receipt has no pair_id: {path}")
        if pair_id in result:
            raise WorkflowError(f"duplicate benchmark pair receipt for {pair_id}: {path}")
        result[pair_id] = (path, value)
    return result


def _seal_executed_attempt(
    *,
    pair: Mapping[str, Any],
    attempt_ref: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence_path = Path(str(attempt_ref.get("evidence") or ""))
    if not evidence_path.is_file():
        raise WorkflowError(
            "benchmark executed-attempt evidence is missing: "
            f"{evidence_path}"
        )
    attempt = read_object(evidence_path)
    if int(attempt.get("attempt", -1)) != int(attempt_ref.get("attempt", -2)):
        raise WorkflowError(
            f"benchmark attempt receipt mismatch: {evidence_path}"
        )
    if str(attempt.get("attempt_id") or "") != str(attempt_ref.get("attempt_id") or ""):
        raise WorkflowError(
            f"benchmark attempt identity mismatch: {evidence_path}"
        )

    arms: list[dict[str, Any]] = []
    arm_refs = attempt.get("arms")
    if not isinstance(arm_refs, dict):
        raise WorkflowError(
            f"benchmark attempt receipt has no arm evidence map: {evidence_path}"
        )
    for arm_name in ("control_raw", "workflow_full"):
        arm_path = Path(str(arm_refs.get(arm_name) or ""))
        if not arm_path.is_file():
            raise WorkflowError(
                f"benchmark executed arm evidence is incomplete: {arm_path}"
            )
        arm_value = read_object(arm_path)
        if str(arm_value.get("arm") or "") != arm_name:
            raise WorkflowError(
                f"benchmark arm receipt identity mismatch: {arm_path}"
            )
        worktree = Path(str(arm_value.get("worktree") or ""))
        stage = Path(str(arm_value.get("stage_dir") or ""))
        if not worktree.is_dir():
            raise WorkflowError(
                f"benchmark executed arm worktree is missing before seal: {worktree}"
            )
        if arm_path != stage / "arm.json":
            raise WorkflowError(
                f"benchmark arm evidence path does not match stage: {arm_path}"
            )
        arms.append(
            {
                "pair_id": str(pair["pair_id"]),
                "case_id": str(pair["case_id"]),
                "repetition": int(pair["repetition"]),
                "attempt": int(attempt_ref["attempt"]),
                "arm": arm_name,
                "arm_receipt": str(arm_path),
                "arm_receipt_sha256": sha256_file(arm_path),
                "worktree": str(worktree),
                "worktree_tree_sha256": _worktree_sha256(worktree),
                "execution_stage": str(stage),
                "execution_stage_inventory": _execution_stage_inventory(stage),
            }
        )
    return arms, {
        "attempt": int(attempt_ref["attempt"]),
        "attempt_id": str(attempt_ref["attempt_id"]),
        "state": str(attempt_ref.get("state") or ""),
        "evidence": str(evidence_path),
        "evidence_sha256": sha256_file(evidence_path),
    }


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
    executed_pairs: list[dict[str, Any]] = []
    receipts = _pair_receipts(run_dir)
    expected_pair_ids = {str(pair["pair_id"]) for pair in plan.get("pairs", [])}
    if set(receipts) != expected_pair_ids:
        missing = sorted(expected_pair_ids - set(receipts))
        extra = sorted(set(receipts) - expected_pair_ids)
        raise WorkflowError(
            "benchmark terminal pair receipts do not match run plan: "
            f"missing={missing}, extra={extra}"
        )

    for pair in plan.get("pairs", []):
        pair_id = str(pair["pair_id"])
        pair_path, pair_receipt = receipts[pair_id]
        if str(pair_receipt.get("case_id") or "") != str(pair["case_id"]):
            raise WorkflowError(f"benchmark pair case mismatch: {pair_path}")
        if int(pair_receipt.get("repetition", -1)) != int(pair["repetition"]):
            raise WorkflowError(f"benchmark pair repetition mismatch: {pair_path}")

        executed_attempts: list[dict[str, Any]] = []
        attempt_refs = pair_receipt.get("attempts")
        if not isinstance(attempt_refs, list) or not attempt_refs:
            raise WorkflowError(
                f"benchmark pair has no executed-attempt receipts: {pair_path}"
            )
        for attempt_ref in attempt_refs:
            if not isinstance(attempt_ref, dict):
                raise WorkflowError(
                    f"benchmark pair has invalid attempt evidence: {pair_path}"
                )
            attempt_arms, attempt_summary = _seal_executed_attempt(
                pair=pair,
                attempt_ref=attempt_ref,
            )
            arms.extend(attempt_arms)
            executed_attempts.append(attempt_summary)

        executed_pairs.append(
            {
                "pair_id": pair_id,
                "pair_receipt": str(pair_path),
                "pair_receipt_sha256": sha256_file(pair_path),
                "selected_attempt": int(pair_receipt["selected_attempt"]),
                "attempts": executed_attempts,
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
        "executed_pairs": executed_pairs,
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

    for pair in seal.get("executed_pairs", []):
        pair_path = Path(str(pair.get("pair_receipt", "")))
        if not pair_path.is_file():
            mismatches.append(
                f"{pair.get('pair_id')}: terminal pair receipt is missing"
            )
        elif sha256_file(pair_path) != pair.get("pair_receipt_sha256"):
            mismatches.append(
                f"{pair.get('pair_id')}: terminal pair receipt changed after seal"
            )
        for attempt in pair.get("attempts", []):
            evidence = Path(str(attempt.get("evidence", "")))
            label = (
                f"{pair.get('pair_id')} attempt={attempt.get('attempt')}"
            )
            if not evidence.is_file():
                mismatches.append(f"{label}: attempt receipt is missing")
            elif sha256_file(evidence) != attempt.get("evidence_sha256"):
                mismatches.append(f"{label}: attempt receipt changed after seal")

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

        arm_receipt = Path(str(item.get("arm_receipt", "")))
        if not arm_receipt.is_file():
            mismatches.append(f"{label}: arm receipt is missing")
        elif sha256_file(arm_receipt) != item.get("arm_receipt_sha256"):
            mismatches.append(f"{label}: arm receipt changed after seal")

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
