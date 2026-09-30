from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .agentic_jev import (
    PILOT_AGENT_MODEL,
    PILOT_AGENT_REASONING_EFFORT,
    PILOT_CODEX_MODEL_CONFIG,
    _read_json_object,
    _receipt_summary,
    _receipt_values,
    _tool_call_functions,
    agentic_jev_skill_sha256,
    build_agentic_jev_solver,
    load_agentic_jev_runtime_lock,
)
from .schema_contracts import validate_instance

EXTERNAL_STUDY_ID = "agentic-jev-external-eval-scout-v1"
INSPECT_EVALS_COMMIT = "b49df6bc9e30b2d24571084bc710b9439b9ffa77"
SWE_BENCH_MINI_REVISION = "b316c349947c29963fce3f4a65967c9807a4b673"


def _git_head(checkout: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError(f"unable to inspect external eval checkout: {checkout}") from exc
    return result.stdout.strip()


def _metadata_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _require_external_sources(checkout: Path, cohort: Mapping[str, Any]) -> None:
    if _git_head(checkout) != INSPECT_EVALS_COMMIT:
        raise WorkflowError("Inspect Evals checkout no longer matches the frozen commit")
    source = cohort.get("sources")
    inspect_source = source.get("inspect_evals") if isinstance(source, Mapping) else None
    if not isinstance(inspect_source, Mapping):
        raise WorkflowError("external cohort has no Inspect Evals source identity")
    if inspect_source.get("commit") != INSPECT_EVALS_COMMIT:
        raise WorkflowError("external cohort Inspect Evals commit does not match runner")
    csv_path = (
        checkout
        / "src"
        / "inspect_evals"
        / "swe_lancer"
        / "data"
        / "all_swelancer_tasks.csv"
    )
    if not csv_path.is_file():
        raise WorkflowError(f"pinned SWE-Lancer CSV is missing: {csv_path}")
    if inspect_source.get("swe_lancer_csv_sha256") != sha256_file(csv_path):
        raise WorkflowError("pinned SWE-Lancer CSV hash no longer matches cohort")

    swe_source = (
        source.get("swe_bench_verified_mini") if isinstance(source, Mapping) else None
    )
    if not isinstance(swe_source, Mapping):
        raise WorkflowError("external cohort has no SWE-bench Mini source identity")
    if swe_source.get("revision") != SWE_BENCH_MINI_REVISION:
        raise WorkflowError("external cohort SWE-bench Mini revision does not match runner")


def _load_external_cohort(path: Path) -> dict[str, Any]:
    value = _read_json_object(path)
    validate_instance(
        value,
        "agent-workflow-benchmark/agentic-jev-external-eval-cohort/v1",
        artifact=str(path),
    )
    cohorts = value.get("cohorts")
    if not isinstance(cohorts, Mapping):
        raise WorkflowError("external cohort has no cohorts object")
    manager = cohorts.get("swe_lancer_manager_choice")
    swebench = cohorts.get("swe_bench_semantic_ambiguity")
    if not isinstance(manager, list) or len(manager) != 6:
        raise WorkflowError("external cohort requires exactly six SWE-Lancer manager tasks")
    if not isinstance(swebench, list) or len(swebench) != 6:
        raise WorkflowError("external cohort requires exactly six SWE-bench Mini tasks")
    ids = [
        str(item.get("id"))
        for group in (manager, swebench)
        for item in group
        if isinstance(item, Mapping)
    ]
    if len(ids) != 12 or len(set(ids)) != 12:
        raise WorkflowError("external cohort requires 12 unique task IDs")
    return value


def _validate_lineage(
    *,
    cohort: Mapping[str, Any],
    prior_manifest_path: Path,
    runtime_lock_path: Path,
    qualification_path: Path,
) -> dict[str, Any]:
    lineage = cohort.get("lineage")
    if not isinstance(lineage, Mapping):
        raise WorkflowError("external cohort has no pilot lineage")
    prior = _read_json_object(prior_manifest_path)
    validate_instance(
        prior,
        "agent-workflow-benchmark/agentic-jev-pilot-run/v1",
        artifact=str(prior_manifest_path),
    )
    if lineage.get("prior_manifest_sha256") != sha256_file(prior_manifest_path):
        raise WorkflowError("external cohort lineage does not match completed pilot")
    c_arm = (prior.get("arms") or {}).get("C-skill-plus-jev")
    if not isinstance(c_arm, Mapping):
        raise WorkflowError("completed pilot has no C arm")
    if c_arm.get("samples") != 24 or c_arm.get("jev_tool_calls") != 0:
        raise WorkflowError("external scout requires the completed 24-sample zero-call C arm")

    runtime = load_agentic_jev_runtime_lock(runtime_lock_path)
    qualification = _read_json_object(qualification_path)
    validate_instance(
        qualification,
        "agent-workflow-benchmark/agentic-jev-tool-qualification/v1",
        artifact=str(qualification_path),
    )
    if qualification.get("qualified") is not True:
        raise WorkflowError("external scout requires a passing Jev qualification")
    if qualification.get("runtime_lock_sha256") != sha256_file(runtime_lock_path):
        raise WorkflowError("external scout qualification does not match runtime lock")
    if qualification.get("skill_sha256") != agentic_jev_skill_sha256():
        raise WorkflowError("external scout qualification used another skill snapshot")
    return runtime


def _activate_pinned_inspect_evals(checkout: Path) -> None:
    source = (checkout / "src").resolve()
    sys.path.insert(0, str(source))
    importlib.invalidate_caches()
    try:
        package = importlib.import_module("inspect_evals")
    except ImportError as exc:
        raise WorkflowError(
            "Inspect Evals dependencies are unavailable; run "
            "scripts/agentic-jev/p2-prepare-external-evals.sh first"
        ) from exc
    package_path = Path(str(getattr(package, "__file__", ""))).resolve()
    try:
        package_path.relative_to(source)
    except ValueError as exc:
        raise WorkflowError(
            f"Inspect Evals imported from unexpected location: {package_path}"
        ) from exc


def _sample_status(log: Any) -> dict[str, int]:
    statuses = {"success": 0, "error": 0}
    for sample in getattr(log, "samples", None) or []:
        if getattr(sample, "error", None):
            statuses["error"] += 1
        else:
            statuses["success"] += 1
    return statuses


def _run_one(
    *,
    source_name: str,
    sample_id: str,
    sample_root: Path,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import inspect_ai
    except ImportError as exc:
        raise WorkflowError("Inspect AI is required for the external Jev scout") from exc

    receipt_path = sample_root / "jev-tool-receipts.jsonl"
    solver = build_agentic_jev_solver(
        arm_id="C-skill-plus-jev",
        codex_version=str(runtime["codex_cli"]["resolved"]),
        receipt_path=receipt_path,
        jev_model=runtime.get("jev_model"),
    )

    if source_name == "swe_lancer_manager_choice":
        try:
            from inspect_evals.swe_lancer import swe_lancer
        except ImportError as exc:
            raise WorkflowError(
                "SWE-Lancer dependencies are unavailable; run the external eval "
                "preparation script"
            ) from exc
        task = swe_lancer(
            task_variant="swe_manager",
            solver=solver,
            epochs=1,
            use_user_tool=False,
            use_per_task_images=False,
            debug=False,
        )
        eval_solver = None
    elif source_name == "swe_bench_semantic_ambiguity":
        try:
            from inspect_evals.swe_bench import swe_bench_verified_mini
        except ImportError as exc:
            raise WorkflowError(
                "SWE-bench dependencies are unavailable; run the external eval "
                "preparation script"
            ) from exc
        # The upstream task function itself pins SWE_BENCH_VERIFIED_MINI_REVISION.
        # Our cohort/source checks assert that this equals the frozen revision.
        task = swe_bench_verified_mini(
            allow_internet=False,
        )
        # SWE-bench's sample/sandbox construction is retained, while the default
        # upstream coding agent is replaced with the already-qualified Codex solver.
        eval_solver = solver
    else:
        raise WorkflowError(f"unknown external cohort source: {source_name}")

    logs = inspect_ai.eval(
        task,
        model=str(runtime["agent_model"]),
        model_args=dict(runtime["agent_model_args"]),
        reasoning_effort=str(runtime["agent_reasoning_effort"]),
        solver=eval_solver,
        sample_id=[sample_id],
        log_dir=str(sample_root / "inspect-logs"),
        log_format="eval",
        max_samples=1,
        max_sandboxes=1,
        max_subprocesses=2,
        fail_on_error=False,
        retry_on_error=0,
        score=False,
        display="plain",
    )
    if len(logs) != 1:
        raise WorkflowError(
            f"external scout sample {sample_id} expected one Inspect log"
        )
    log = logs[0]
    log_samples = getattr(log, "samples", None) or []
    if len(log_samples) != 1:
        raise WorkflowError(
            f"external scout sample {sample_id} expected one completed sample; "
            f"observed {len(log_samples)}"
        )
    receipts = _receipt_values(receipt_path)
    return {
        "sample_id": sample_id,
        "source": source_name,
        "inspect_log": getattr(log, "location", None),
        "sample_status": _sample_status(log),
        "outer_tool_functions": _tool_call_functions(log),
        "tool_function_evidence_scope": "outer-codex-transcript-diagnostic-only",
        "jev_execution_evidence": "host-tool-receipt",
        "jev_tool_calls": len(receipts),
        "tool_receipts": _receipt_summary(receipt_path),
    }


def run_external_jev_scout(
    *,
    output_root: Path,
    cohort_path: Path,
    inspect_evals_checkout: Path,
    prior_manifest_path: Path,
    runtime_lock_path: Path,
    qualification_path: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    manifest_path = output_root / "run-manifest.json"
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "external Jev scout output directory is not empty; preserve the "
            f"existing attempt before retrying: {output_root}"
        )

    cohort_path = Path(cohort_path)
    checkout = Path(inspect_evals_checkout)
    prior_manifest_path = Path(prior_manifest_path)
    runtime_lock_path = Path(runtime_lock_path)
    qualification_path = Path(qualification_path)

    cohort = _load_external_cohort(cohort_path)
    _require_external_sources(checkout, cohort)
    runtime = _validate_lineage(
        cohort=cohort,
        prior_manifest_path=prior_manifest_path,
        runtime_lock_path=runtime_lock_path,
        qualification_path=qualification_path,
    )
    _activate_pinned_inspect_evals(checkout)

    if runtime["agent_model"] != PILOT_AGENT_MODEL:
        raise WorkflowError("external scout model no longer matches the pilot")
    if runtime["agent_reasoning_effort"] != PILOT_AGENT_REASONING_EFFORT:
        raise WorkflowError("external scout reasoning effort no longer matches the pilot")
    if runtime["codex_model_config"] != PILOT_CODEX_MODEL_CONFIG:
        raise WorkflowError("external scout Codex configuration no longer matches pilot")

    output_root.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    cohorts = cohort["cohorts"]
    for source_name in (
        "swe_lancer_manager_choice",
        "swe_bench_semantic_ambiguity",
    ):
        for entry in cohorts[source_name]:
            sample_id = str(entry["id"])
            sample_root = output_root / source_name / sample_id
            sample_root.mkdir(parents=True, exist_ok=False)
            result = _run_one(
                source_name=source_name,
                sample_id=sample_id,
                sample_root=sample_root,
                runtime=runtime,
            )
            samples.append(result)
            # Persist progress after each immutable per-sample attempt.
            atomic_write_json(sample_root / "sample-result.json", result)

    total_calls = sum(int(item["jev_tool_calls"]) for item in samples)
    successful_samples = sum(
        int(item["sample_status"]["success"]) for item in samples
    )
    errored_samples = sum(int(item["sample_status"]["error"]) for item in samples)
    called_ids = [
        str(item["sample_id"]) for item in samples if item["jev_tool_calls"] > 0
    ]
    manifest = {
        "schema": "agent-workflow-benchmark/agentic-jev-external-eval-run/v1",
        "study_id": EXTERNAL_STUDY_ID,
        "development_only": True,
        "cohort_sha256": sha256_file(cohort_path),
        "runtime_lock_sha256": sha256_file(runtime_lock_path),
        "qualification_sha256": sha256_file(qualification_path),
        "prior_pilot_manifest_sha256": sha256_file(prior_manifest_path),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "runtime": {
            "model": runtime["agent_model"],
            "reasoning_effort": runtime["agent_reasoning_effort"],
            "codex_version": runtime["codex_cli"]["resolved"],
            "codex_model_config": runtime["codex_model_config"],
            "skill_sha256": agentic_jev_skill_sha256(),
        },
        "external_sources": {
            "inspect_evals_commit": INSPECT_EVALS_COMMIT,
            "inspect_evals_distribution_version": _metadata_version("inspect-evals"),
            "swe_bench_mini_revision": SWE_BENCH_MINI_REVISION,
        },
        "execution": {
            "arm": "C-skill-plus-jev",
            "samples_expected": 12,
            "samples_observed": len(samples),
            "success": successful_samples,
            "errors": errored_samples,
            "jev_tool_calls": total_calls,
            "samples_with_jev_calls": called_ids,
            "scoring_enabled": False,
        },
        "samples": samples,
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "purpose": "stress-test spontaneous Jev uptake on established public evals",
        },
    }
    validate_instance(
        manifest,
        "agent-workflow-benchmark/agentic-jev-external-eval-run/v1",
        artifact="Agentic Jev external eval scout run",
    )
    atomic_write_json(manifest_path, manifest)
    return {"path": str(manifest_path), **manifest}
