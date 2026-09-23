from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file, utc_now
from .common import copy_tree, file_inventory, read_object, verify_manifest, write_manifest
from .contracts import BENCHMARK_CONSOLIDATION_SCHEMA, validate_value
from .events import append_event
from .pairing import attempts_for, selected_arms


def _copy_verified(source: Path, destination: Path) -> list[dict[str, Any]]:
    if destination.exists():
        shutil.rmtree(destination)
    copy_tree(source, destination)
    source_inventory = file_inventory(source)
    destination_inventory = file_inventory(destination)
    source_index = {item["path"]: item for item in source_inventory}
    destination_index = {item["path"]: item for item in destination_inventory}
    if source_index.keys() != destination_index.keys():
        raise WorkflowError(f"consolidation file set mismatch for {source}")
    mappings: list[dict[str, Any]] = []
    for relative in sorted(source_index):
        left = source_index[relative]
        right = destination_index[relative]
        if left["sha256"] != right["sha256"] or left["bytes"] != right["bytes"]:
            raise WorkflowError(f"consolidation digest mismatch for {source / relative}")
        mappings.append(
            {
                "source": str(source / relative),
                "destination": str(destination / relative),
                "relative_path": relative,
                "sha256": left["sha256"],
                "bytes": left["bytes"],
            }
        )
    return mappings


def consolidate_run(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    coordinator = Path(plan["coordinator"]["worktree"]).resolve()
    existing_receipt = run_dir / "consolidation-receipt.json"
    if existing_receipt.is_file():
        verification = verify_consolidated_run(run_dir)
        if verification["valid"]:
            receipt = read_object(existing_receipt)
            return {
                "run_id": plan["run_id"],
                "run_dir": str(run_dir),
                "pairs": receipt["pairs"],
                "artifacts": len(receipt["artifacts"]),
                "receipt": str(existing_receipt),
                "manifest": str(run_dir / "MANIFEST.sha256"),
                "existing": True,
            }
    try:
        run_dir.resolve().relative_to(coordinator)
    except ValueError as exc:
        raise WorkflowError("benchmark consolidation target is outside coordinator worktree") from exc
    append_event(run_dir, event_type="consolidation_started", run_id=str(plan["run_id"]))
    mappings: list[dict[str, Any]] = []
    pair_count = 0
    for pair in plan["pairs"]:
        pair_destination = run_dir / "pairs" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}"
        pair_destination.mkdir(parents=True, exist_ok=True)
        pair_state = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / "pair.json"
        if not pair_state.is_file():
            raise WorkflowError(f"pair evidence missing: {pair_state}")
        shutil.copy2(pair_state, pair_destination / "pair.json")
        mappings.append(
            {
                "source": str(pair_state),
                "destination": str(pair_destination / "pair.json"),
                "relative_path": f"pairs/{pair['case_id']}/r{int(pair['repetition']):02d}/pair.json",
                "sha256": sha256_file(pair_state),
                "bytes": pair_state.stat().st_size,
            }
        )
        pair_state_value = read_object(pair_state)
        selected = selected_arms(pair, pair_state_value)
        # Preserve every attempted run for retry and infrastructure analysis.
        for attempt in attempts_for(pair):
            attempt_destination = pair_destination / "attempts" / f"attempt-{int(attempt['attempt']):02d}"
            evidence_path = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / f"attempt-{int(attempt['attempt']):02d}" / "attempt.json"
            if not evidence_path.is_file():
                continue
            attempt_destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(evidence_path, attempt_destination / "attempt.json")
            mappings.append({
                "source": str(evidence_path), "destination": str(attempt_destination / "attempt.json"),
                "relative_path": str((attempt_destination / "attempt.json").relative_to(run_dir)),
                "sha256": sha256_file(evidence_path), "bytes": evidence_path.stat().st_size,
            })
            attempt_value = read_object(evidence_path)
            for review in attempt_value.get("phase_reviews", []):
                source_review = Path(str(review["path"]))
                if not source_review.is_file() or sha256_file(source_review) != review.get("sha256"):
                    raise WorkflowError(f"phase review missing or changed: {source_review}")
                review_destination = attempt_destination / "phase-reviews" / source_review.name
                review_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_review, review_destination)
                mappings.append({
                    "source": str(source_review), "destination": str(review_destination),
                    "relative_path": str(review_destination.relative_to(run_dir)),
                    "sha256": review["sha256"], "bytes": review_destination.stat().st_size,
                })
            for arm_name in ("control_raw", "workflow_full"):
                source = Path(attempt["arms"][arm_name]["stage_dir"])
                if not (source / "arm.json").is_file():
                    continue
                mappings.extend(_copy_verified(source, attempt_destination / arm_name))
        # Stable selected-arm aliases keep scoring/review/reporting independent of retry count.
        for arm_name in ("control_raw", "workflow_full"):
            source = Path(selected[arm_name]["stage_dir"])
            if not (source / "arm.json").is_file():
                raise WorkflowError(f"arm evidence missing: {source / 'arm.json'}")
            destination = pair_destination / arm_name
            mappings.extend(_copy_verified(source, destination))
            inventory = file_inventory(destination)
            atomic_write_json(destination / "artifact-inventory.json", {"artifacts": inventory})
        pair_count += 1
    receipt = {
        "schema": BENCHMARK_CONSOLIDATION_SCHEMA,
        "run_id": plan["run_id"],
        "benchmark_id": plan["benchmark_id"],
        "coordinator_worktree": str(coordinator),
        "run_directory": str(run_dir),
        "pairs": pair_count,
        "artifacts": mappings,
        "completed_at": utc_now(),
    }
    validate_value(receipt, BENCHMARK_CONSOLIDATION_SCHEMA, "benchmark consolidation receipt")
    atomic_write_json(run_dir / "consolidation-receipt.json", receipt)
    append_event(
        run_dir,
        event_type="consolidation_terminal",
        run_id=str(plan["run_id"]),
        payload={"pairs": pair_count, "artifacts": len(mappings)},
    )
    write_manifest(run_dir)
    return {
        "run_id": plan["run_id"],
        "run_dir": str(run_dir),
        "pairs": pair_count,
        "artifacts": len(mappings),
        "receipt": str(run_dir / "consolidation-receipt.json"),
        "manifest": str(run_dir / "MANIFEST.sha256"),
    }


def verify_consolidated_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    receipt_path = run_dir / "consolidation-receipt.json"
    if not receipt_path.is_file():
        raise WorkflowError(f"consolidation receipt is missing: {receipt_path}")
    receipt = read_object(receipt_path)
    validate_value(receipt, BENCHMARK_CONSOLIDATION_SCHEMA, "benchmark consolidation receipt")
    receipt_failures: list[str] = []
    for item in receipt["artifacts"]:
        destination = Path(item["destination"])
        if not destination.is_file():
            receipt_failures.append(item["relative_path"] + ":missing")
        elif sha256_file(destination) != item["sha256"]:
            receipt_failures.append(item["relative_path"] + ":changed")
    manifest = verify_manifest(run_dir)
    return {
        "run_id": receipt["run_id"],
        "valid": manifest["valid"] and not receipt_failures,
        "manifest": manifest,
        "receipt_failures": receipt_failures,
        "artifacts": len(receipt["artifacts"]),
    }
