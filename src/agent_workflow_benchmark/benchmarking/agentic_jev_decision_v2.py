from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .agentic_jev import (
    PILOT_CODEX_MODEL_CONFIG,
    TOOL_RECEIPT_SCHEMA,
    _read_json_object,
    _receipt_summary,
    _receipt_values,
    _tool_call_functions,
    agentic_jev_skill_path,
    agentic_jev_skill_sha256,
    build_agentic_jev_solver,
    jev_bridged_tool,
    load_agentic_jev_runtime_lock,
)
from .agentic_jev_external import (
    INSPECT_EVALS_COMMIT,
    _activate_pinned_inspect_evals,
    _load_external_cohort,
    _require_external_sources,
    _sample_status,
)
from .schema_contracts import validate_instance

STUDY_ID = "agentic-jev-decision-skill-v2"
LOCK_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v2-lock/v1"
QUAL_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v2-qualification/v1"
RUN_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v2-manager-run/v1"

_ACTIVATION_PROMPT = """You are reviewing an implementation decision.

The product must preserve legacy client compatibility while exposing a previously
collapsed 'unknown' state to newer clients. Repository inspection has established
that old clients treat a missing value as false, newer clients can represent an
explicit unknown state, and both behaviors must remain supported.

Choose the best implementation proposal:

- proposal_1: Continue coercing missing values to false everywhere.
- proposal_2: Preserve legacy coercion at the compatibility boundary but represent
  unknown explicitly in the newer internal/API path.
- proposal_3: Reject legacy payloads that omit the value so all callers migrate.

Return the selected proposal ID and a short reason. Do not edit files.
"""


def decision_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v2/jev-decision-support/SKILL.md"
    )
    return Path(str(resource))


def decision_skill_sha256() -> str:
    return sha256_file(decision_skill_path())


def _load_bridge_qualification(
    path: Path, *, base_runtime_lock_path: Path
) -> dict[str, Any]:
    value = _read_json_object(path)
    validate_instance(
        value,
        "agent-workflow-benchmark/agentic-jev-tool-qualification/v1",
        artifact=str(path),
    )
    if value.get("qualified") is not True:
        raise WorkflowError("decision-skill v2 requires a passing bridge qualification")
    if value.get("runtime_lock_sha256") != sha256_file(base_runtime_lock_path):
        raise WorkflowError("bridge qualification does not match the base runtime lock")
    if value.get("skill_sha256") != agentic_jev_skill_sha256():
        raise WorkflowError("bridge qualification used a different upstream skill")
    return value


def create_decision_v2_lock(
    *,
    destination: Path,
    base_runtime_lock_path: Path,
    bridge_qualification_path: Path,
    cohort_path: Path,
    inspect_evals_checkout: Path,
) -> dict[str, Any]:
    destination = Path(destination)
    if destination.exists():
        raise WorkflowError(f"decision-skill v2 lock already exists: {destination}")

    base_runtime_lock_path = Path(base_runtime_lock_path)
    bridge_qualification_path = Path(bridge_qualification_path)
    cohort_path = Path(cohort_path)
    inspect_evals_checkout = Path(inspect_evals_checkout)

    runtime = load_agentic_jev_runtime_lock(base_runtime_lock_path)
    _load_bridge_qualification(
        bridge_qualification_path,
        base_runtime_lock_path=base_runtime_lock_path,
    )
    cohort = _load_external_cohort(cohort_path)
    _require_external_sources(inspect_evals_checkout, cohort)

    record = {
        "schema": LOCK_SCHEMA,
        "study_id": STUDY_ID,
        "base_runtime_lock": {
            "path": str(base_runtime_lock_path.resolve()),
            "sha256": sha256_file(base_runtime_lock_path),
        },
        "bridge_qualification": {
            "path": str(bridge_qualification_path.resolve()),
            "sha256": sha256_file(bridge_qualification_path),
        },
        "external_cohort": {
            "path": str(cohort_path.resolve()),
            "sha256": sha256_file(cohort_path),
            "inspect_evals_commit": INSPECT_EVALS_COMMIT,
        },
        "runtime": {
            "model": runtime["agent_model"],
            "reasoning_effort": runtime["agent_reasoning_effort"],
            "codex_version": runtime["codex_cli"]["resolved"],
            "codex_model_config": runtime["codex_model_config"],
            "jev_model": runtime.get("jev_model"),
        },
        "skills": {
            "upstream_typesafe_sha256": agentic_jev_skill_sha256(),
            "decision_support_sha256": decision_skill_sha256(),
        },
        "host_tool": {
            "implementation_sha256": runtime["host_tool"]["implementation_sha256"],
            "receipt_schema": TOOL_RECEIPT_SCHEMA,
        },
        "claim_boundary": {
            "exploratory_only": True,
            "supersedes_prior_zero_uptake_result": False,
            "purpose": (
                "freeze an additive agent-facing Jev decision workflow after the "
                "generic TypeSafe integration skill produced zero spontaneous uptake"
            ),
        },
    }
    validate_instance(record, LOCK_SCHEMA, artifact="decision-skill v2 lock")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), **record}


def load_decision_v2_lock(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _read_json_object(path)
    validate_instance(value, LOCK_SCHEMA, artifact=str(path))

    base_lock_path = Path(str(value["base_runtime_lock"]["path"]))
    if not base_lock_path.is_file():
        raise WorkflowError("decision-skill v2 base runtime lock is missing")
    if sha256_file(base_lock_path) != value["base_runtime_lock"]["sha256"]:
        raise WorkflowError("decision-skill v2 base runtime lock hash changed")
    runtime = load_agentic_jev_runtime_lock(base_lock_path)

    bridge_path = Path(str(value["bridge_qualification"]["path"]))
    if not bridge_path.is_file():
        raise WorkflowError("decision-skill v2 bridge qualification is missing")
    if sha256_file(bridge_path) != value["bridge_qualification"]["sha256"]:
        raise WorkflowError("decision-skill v2 bridge qualification hash changed")
    _load_bridge_qualification(bridge_path, base_runtime_lock_path=base_lock_path)

    cohort_path = Path(str(value["external_cohort"]["path"]))
    if not cohort_path.is_file():
        raise WorkflowError("decision-skill v2 external cohort is missing")
    if sha256_file(cohort_path) != value["external_cohort"]["sha256"]:
        raise WorkflowError("decision-skill v2 external cohort hash changed")

    if value["skills"]["upstream_typesafe_sha256"] != agentic_jev_skill_sha256():
        raise WorkflowError("decision-skill v2 upstream TypeSafe skill changed")
    if value["skills"]["decision_support_sha256"] != decision_skill_sha256():
        raise WorkflowError("decision-skill v2 decision support skill changed")
    if value["host_tool"]["implementation_sha256"] != runtime["host_tool"]["implementation_sha256"]:
        raise WorkflowError("decision-skill v2 host tool changed")
    return value, runtime


def build_decision_v2_solver(
    *,
    runtime: Mapping[str, Any],
    receipt_path: Path,
) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError(
            "decision-skill v2 requires agent-workflow-benchmark[agentic-jev]"
        ) from exc

    return codex_cli(
        version=str(runtime["codex_cli"]["resolved"]),
        model_config=PILOT_CODEX_MODEL_CONFIG,
        skills=[
            agentic_jev_skill_path().parent,
            decision_skill_path().parent,
        ],
        bridged_tools=[
            BridgedToolsSpec(
                name="jev",
                tools=[
                    jev_bridged_tool(
                        receipt_path=receipt_path,
                        model=runtime.get("jev_model"),
                    )
                ],
            )
        ],
        web_search="disabled",
        goals=False,
        attempts=1,
        mcp_servers=[],
        auto_review=False,
        home_dir="/tmp/codex-home",
        system_prompt=(
            "Complete the assigned coding task using only the supplied repository "
            "state and available tools. Use installed skills and optional semantic "
            "tools only when they materially improve a bounded decision; do not "
            "add dependencies or product code merely to access an experimental tool."
        ),
        config_overrides={
            "approval_policy": "never",
            "web_search": "disabled",
        },
    )


def _transcript_contains_secret(log: Any) -> bool:
    import os

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return False
    samples = getattr(log, "samples", None) or []
    transcript = json.dumps(
        [
            getattr(message, "model_dump", lambda: {"text": str(message)})()
            for sample in samples
            for message in (getattr(sample, "messages", None) or [])
        ],
        ensure_ascii=False,
        default=str,
    )
    return api_key in transcript


def _run_activation_arm(
    *,
    arm: str,
    output_root: Path,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_ai import Task
        from inspect_ai.dataset import Sample
    except ImportError as exc:
        raise WorkflowError("decision-skill v2 qualification requires Inspect AI") from exc

    root = output_root / arm
    root.mkdir(parents=True, exist_ok=False)
    receipt_path = root / "jev-tool-receipts.jsonl"

    if arm == "old-treatment-control":
        solver = build_agentic_jev_solver(
            arm_id="C-skill-plus-jev",
            codex_version=str(runtime["codex_cli"]["resolved"]),
            receipt_path=receipt_path,
            jev_model=runtime.get("jev_model"),
        )
    elif arm == "decision-skill-v2":
        solver = build_decision_v2_solver(
            runtime=runtime,
            receipt_path=receipt_path,
        )
    else:
        raise WorkflowError(f"unknown decision-skill qualification arm: {arm}")

    from .inspect_adjudication import _inspect_sandbox_spec

    task = Task(
        dataset=[
            Sample(
                id=f"decision-skill-activation-{arm}",
                input=_ACTIVATION_PROMPT,
                files={"README.md": "Synthetic bounded implementation-choice fixture.\n"},
            )
        ],
        solver=solver,
        sandbox=_inspect_sandbox_spec(),
        checkpoint=False,
    )
    logs = inspect_ai.eval(
        task,
        model=str(runtime["agent_model"]),
        model_args=dict(runtime["agent_model_args"]),
        reasoning_effort=str(runtime["agent_reasoning_effort"]),
        log_dir=str(root / "inspect-logs"),
        log_format="eval",
        max_samples=1,
        max_sandboxes=1,
        max_subprocesses=2,
        fail_on_error=True,
        retry_on_error=0,
        score=False,
        display="plain",
    )
    if len(logs) != 1:
        raise WorkflowError(f"decision-skill activation arm {arm} produced no log")
    log = logs[0]
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1 or getattr(samples[0], "error", None):
        raise WorkflowError(f"decision-skill activation arm {arm} failed")
    receipts = _receipt_values(receipt_path)
    successful = [item for item in receipts if item.get("status") == "success"]
    return {
        "arm": arm,
        "inspect_log": getattr(log, "location", None),
        "outer_tool_functions": _tool_call_functions(log),
        "jev_tool_calls": len(receipts),
        "successful_jev_calls": len(successful),
        "receipt_summary": _receipt_summary(receipt_path),
        "api_key_absent_from_transcript": not _transcript_contains_secret(log),
    }


def run_decision_v2_activation_qualification(
    *,
    output_root: Path,
    v2_lock_path: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "decision-skill v2 qualification root is not empty; preserve the "
            f"existing attempt before retrying: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    lock, runtime = load_decision_v2_lock(v2_lock_path)
    if "jev" in _ACTIVATION_PROMPT.lower() or "typesafe" in _ACTIVATION_PROMPT.lower():
        raise WorkflowError("activation prompt must not explicitly name Jev or TypeSafe")

    control = _run_activation_arm(
        arm="old-treatment-control",
        output_root=output_root,
        runtime=runtime,
    )
    treatment = _run_activation_arm(
        arm="decision-skill-v2",
        output_root=output_root,
        runtime=runtime,
    )
    qualified = (
        treatment["jev_tool_calls"] == 1
        and treatment["successful_jev_calls"] == 1
        and treatment["api_key_absent_from_transcript"] is True
    )
    record = {
        "schema": QUAL_SCHEMA,
        "study_id": STUDY_ID,
        "qualified": qualified,
        "v2_lock_sha256": sha256_file(v2_lock_path),
        "activation_prompt_explicitly_names_jev": False,
        "activation_prompt_explicitly_names_typesafe": False,
        "control": control,
        "treatment": treatment,
        "activation_lift_observed": (
            control["jev_tool_calls"] == 0 and treatment["jev_tool_calls"] == 1
        ),
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "qualification_only_tests_skill_activation": True,
        },
    }
    validate_instance(record, QUAL_SCHEMA, artifact="decision-skill v2 qualification")
    result_path = output_root / "qualification.json"
    atomic_write_json(result_path, record)
    if not qualified:
        raise WorkflowError(
            "decision-skill v2 activation qualification failed; inspect qualification.json"
        )
    return {"path": str(result_path), **record}


def _run_manager_sample_v2(
    *,
    sample_id: str,
    sample_root: Path,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_evals.swe_lancer import swe_lancer
    except ImportError as exc:
        raise WorkflowError("decision-skill v2 manager run requires Inspect Evals") from exc

    receipt_path = sample_root / "jev-tool-receipts.jsonl"
    solver = build_decision_v2_solver(runtime=runtime, receipt_path=receipt_path)
    task = swe_lancer(
        task_variant="swe_manager",
        solver=solver,
        epochs=1,
        use_user_tool=False,
        use_per_task_images=False,
        debug=False,
    )
    logs = inspect_ai.eval(
        task,
        model=str(runtime["agent_model"]),
        model_args=dict(runtime["agent_model_args"]),
        reasoning_effort=str(runtime["agent_reasoning_effort"]),
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
        raise WorkflowError(f"decision-skill v2 sample {sample_id} produced no log")
    log = logs[0]
    log_samples = getattr(log, "samples", None) or []
    if len(log_samples) != 1:
        raise WorkflowError(
            f"decision-skill v2 sample {sample_id} expected one sample; "
            f"observed {len(log_samples)}"
        )
    receipts = _receipt_values(receipt_path)
    return {
        "sample_id": sample_id,
        "sample_status": _sample_status(log),
        "inspect_log": getattr(log, "location", None),
        "jev_tool_calls": len(receipts),
        "tool_receipts": _receipt_summary(receipt_path),
        "outer_tool_functions": _tool_call_functions(log),
        "jev_execution_evidence": "host-tool-receipt",
    }


def run_decision_v2_manager_gate(
    *,
    output_root: Path,
    v2_lock_path: Path,
    activation_qualification_path: Path,
    inspect_evals_checkout: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "decision-skill v2 manager run root is not empty; preserve the "
            f"existing attempt before retrying: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    lock, runtime = load_decision_v2_lock(v2_lock_path)
    qualification = _read_json_object(activation_qualification_path)
    validate_instance(
        qualification,
        QUAL_SCHEMA,
        artifact=str(activation_qualification_path),
    )
    if qualification.get("qualified") is not True:
        raise WorkflowError("decision-skill v2 activation qualification is not passing")
    if qualification.get("v2_lock_sha256") != sha256_file(v2_lock_path):
        raise WorkflowError("decision-skill v2 qualification used another lock")

    cohort_path = Path(str(lock["external_cohort"]["path"]))
    cohort = _load_external_cohort(cohort_path)
    checkout = Path(inspect_evals_checkout)
    _require_external_sources(checkout, cohort)
    _activate_pinned_inspect_evals(checkout)

    manager = cohort["cohorts"]["swe_lancer_manager_choice"]
    samples: list[dict[str, Any]] = []
    for entry in manager:
        sample_id = str(entry["id"])
        sample_root = output_root / sample_id
        sample_root.mkdir(parents=True, exist_ok=False)
        result = _run_manager_sample_v2(
            sample_id=sample_id,
            sample_root=sample_root,
            runtime=runtime,
        )
        atomic_write_json(sample_root / "sample-result.json", result)
        samples.append(result)

    total_calls = sum(int(item["jev_tool_calls"]) for item in samples)
    called_ids = [
        str(item["sample_id"]) for item in samples if item["jev_tool_calls"] > 0
    ]
    success = sum(int(item["sample_status"]["success"]) for item in samples)
    errors = sum(int(item["sample_status"]["error"]) for item in samples)
    record = {
        "schema": RUN_SCHEMA,
        "study_id": STUDY_ID,
        "development_only": True,
        "v2_lock_sha256": sha256_file(v2_lock_path),
        "activation_qualification_sha256": sha256_file(
            activation_qualification_path
        ),
        "execution": {
            "arm": "typesafe-plus-jev-decision-skill",
            "source": "swe_lancer_manager_choice",
            "samples_expected": 6,
            "samples_observed": len(samples),
            "success": success,
            "errors": errors,
            "jev_tool_calls": total_calls,
            "samples_with_jev_calls": called_ids,
            "scoring_enabled": False,
        },
        "samples": samples,
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "prior_zero_uptake_runs_preserved": True,
        },
    }
    validate_instance(record, RUN_SCHEMA, artifact="decision-skill v2 manager run")
    result_path = output_root / "run-manifest.json"
    atomic_write_json(result_path, record)
    return {"path": str(result_path), **record}
