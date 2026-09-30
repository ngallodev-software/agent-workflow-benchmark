from __future__ import annotations

import hashlib
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
    jev_bridged_tool,
)
from .agentic_jev_decision_v2 import (
    ACTIVATION_PROTOCOL_ID as V2_ACTIVATION_PROTOCOL_ID,
    QUAL_SCHEMA as V2_QUAL_SCHEMA,
    activation_protocol_sha256 as v2_activation_protocol_sha256,
    build_decision_v2_solver,
    load_decision_v2_lock,
)
from .agentic_jev_external import (
    _activate_pinned_inspect_evals,
    _load_external_cohort,
    _require_external_sources,
    _sample_status,
)
from .schema_contracts import validate_instance

STUDY_ID = "agentic-jev-decision-skill-v3"
LOCK_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v3-lock/v1"
QUAL_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v3-qualification/v1"
CANARY_SCHEMA = "agent-workflow-benchmark/agentic-jev-decision-v3-manager-canary/v1"

DECISION_SKILL_SOURCE_REPOSITORY = "ngallodev-software/jev-decision-support"
DECISION_SKILL_SOURCE_COMMIT = "65b444965e48209860e353f2aa0e8d9dbe35d2ce"
DECISION_SKILL_SOURCE_PATH = "skills/jev-decision-support/SKILL.md"

ACTIVATION_PROTOCOL_ID = "tentative-leader-second-order-v1"
CANARY_COUNT = 2

_ACTIVATION_PROMPT = """You are reviewing an implementation decision.

Repository inspection and an exact compatibility test establish that proposal_2 is
the only proposal that preserves the required legacy behavior. Therefore proposal_2
must be selected.

However, the change touches a shared normalization path used by several callers.
The available repository evidence shows that rollback is possible, but there is no
exact specification or test that answers whether the evidence is sufficient to
finalize the change without additional investigation, nor how much qualitative
implementation risk the shared-path change introduces.

Select the required proposal and state whether the current evidence is sufficient to
finalize without additional investigation. Briefly identify any material risk that
should affect review. Do not edit files.

- proposal_1: Keep normalization duplicated at each call site. This fails the exact
  compatibility test for one legacy path.
- proposal_2: Normalize at the shared compatibility boundary. This is the only
  proposal that passes the exact compatibility test, but it affects several callers.
- proposal_3: Reject legacy payloads and require migration. This violates the exact
  compatibility requirement.
"""


def decision_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v3/jev-decision-support/SKILL.md"
    )
    return Path(str(resource))


def decision_skill_sha256() -> str:
    return sha256_file(decision_skill_path())


def decision_skill_interface_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v3/jev-decision-support/agents/openai.yaml"
    )
    return Path(str(resource))


def decision_skill_interface_sha256() -> str:
    return sha256_file(decision_skill_interface_path())


def activation_protocol_record() -> dict[str, object]:
    return {
        "id": ACTIVATION_PROTOCOL_ID,
        "prompt": _ACTIVATION_PROMPT,
        "prompt_explicitly_names_jev": False,
        "prompt_explicitly_names_typesafe": False,
        "proposal_deterministically_resolved": "proposal_2",
        "remaining_semantic_questions": [
            "evidence sufficiency",
            "qualitative implementation risk",
        ],
    }


def activation_protocol_sha256() -> str:
    payload = json.dumps(
        activation_protocol_record(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_v2_qualification(
    path: Path, *, v2_lock_path: Path
) -> dict[str, Any]:
    value = _read_json_object(path)
    validate_instance(value, V2_QUAL_SCHEMA, artifact=str(path))
    if value.get("qualified") is not True:
        raise WorkflowError("decision-skill v3 requires passing v2 activation")
    if value.get("v2_lock_sha256") != sha256_file(v2_lock_path):
        raise WorkflowError("v2 activation qualification does not match v2 lock")
    protocol = value.get("activation_protocol")
    if not isinstance(protocol, Mapping):
        raise WorkflowError("v2 qualification has no activation protocol")
    if protocol.get("id") != V2_ACTIVATION_PROTOCOL_ID:
        raise WorkflowError("v2 qualification used unexpected activation protocol")
    if protocol.get("sha256") != v2_activation_protocol_sha256():
        raise WorkflowError("v2 activation protocol hash changed")
    return value


def _load_v2_manager_run(path: Path, *, v2_lock_path: Path) -> dict[str, Any]:
    value = _read_json_object(path)
    validate_instance(
        value,
        "agent-workflow-benchmark/agentic-jev-decision-v2-manager-run/v1",
        artifact=str(path),
    )
    if value.get("v2_lock_sha256") != sha256_file(v2_lock_path):
        raise WorkflowError("v2 manager run does not match v2 lock")
    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        raise WorkflowError("v2 manager run has no execution object")
    if execution.get("samples_observed") != 6 or execution.get("success") != 6:
        raise WorkflowError("v2 manager lineage requires six successful samples")
    if execution.get("jev_tool_calls") != 0:
        raise WorkflowError("v3 treatment is defined as follow-up to v2 zero uptake")
    return value


def create_decision_v3_lock(
    *,
    destination: Path,
    v2_lock_path: Path,
    v2_qualification_path: Path,
    v2_manager_run_path: Path,
) -> dict[str, Any]:
    destination = Path(destination)
    if destination.exists():
        raise WorkflowError(f"decision-skill v3 lock already exists: {destination}")

    v2_lock_path = Path(v2_lock_path)
    v2_qualification_path = Path(v2_qualification_path)
    v2_manager_run_path = Path(v2_manager_run_path)

    v2_lock, runtime = load_decision_v2_lock(v2_lock_path)
    _load_v2_qualification(v2_qualification_path, v2_lock_path=v2_lock_path)
    _load_v2_manager_run(v2_manager_run_path, v2_lock_path=v2_lock_path)

    record = {
        "schema": LOCK_SCHEMA,
        "study_id": STUDY_ID,
        "parent_v2": {
            "lock_path": str(v2_lock_path.resolve()),
            "lock_sha256": sha256_file(v2_lock_path),
            "qualification_path": str(v2_qualification_path.resolve()),
            "qualification_sha256": sha256_file(v2_qualification_path),
            "manager_run_path": str(v2_manager_run_path.resolve()),
            "manager_run_sha256": sha256_file(v2_manager_run_path),
            "manager_run_jev_calls": 0,
        },
        "runtime": {
            "model": runtime["agent_model"],
            "reasoning_effort": runtime["agent_reasoning_effort"],
            "codex_version": runtime["codex_cli"]["resolved"],
            "codex_model_config": runtime["codex_model_config"],
            "jev_model": runtime.get("jev_model"),
        },
        "external_cohort": dict(v2_lock["external_cohort"]),
        "skills": {
            "upstream_typesafe_sha256": agentic_jev_skill_sha256(),
            "decision_support_sha256": decision_skill_sha256(),
            "decision_support_interface_sha256": decision_skill_interface_sha256(),
            "decision_support_source": {
                "repository": DECISION_SKILL_SOURCE_REPOSITORY,
                "commit": DECISION_SKILL_SOURCE_COMMIT,
                "path": DECISION_SKILL_SOURCE_PATH,
            },
        },
        "host_tool": {
            "implementation_sha256": runtime["host_tool"]["implementation_sha256"],
            "receipt_schema": TOOL_RECEIPT_SCHEMA,
        },
        "policy_delta": {
            "v2": (
                "Jev only when deterministic evidence fails to identify one answer"
            ),
            "v3": (
                "Jev may also judge evidence sufficiency or semantic risk after a "
                "tentative answer, while exact deterministic authority remains controlling"
            ),
        },
        "claim_boundary": {
            "exploratory_only": True,
            "supersedes_v2_result": False,
            "effectiveness_claim_allowed": False,
        },
    }
    validate_instance(record, LOCK_SCHEMA, artifact="decision-skill v3 lock")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), **record}


def load_decision_v3_lock(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _read_json_object(path)
    validate_instance(value, LOCK_SCHEMA, artifact=str(path))

    parent = value["parent_v2"]
    v2_lock_path = Path(str(parent["lock_path"]))
    v2_qualification_path = Path(str(parent["qualification_path"]))
    v2_manager_run_path = Path(str(parent["manager_run_path"]))

    for key, p in (
        ("lock_sha256", v2_lock_path),
        ("qualification_sha256", v2_qualification_path),
        ("manager_run_sha256", v2_manager_run_path),
    ):
        if not p.is_file():
            raise WorkflowError(f"decision-skill v3 lineage file missing: {p}")
        if sha256_file(p) != parent[key]:
            raise WorkflowError(f"decision-skill v3 lineage hash changed: {p}")

    _, runtime = load_decision_v2_lock(v2_lock_path)
    _load_v2_qualification(v2_qualification_path, v2_lock_path=v2_lock_path)
    _load_v2_manager_run(v2_manager_run_path, v2_lock_path=v2_lock_path)

    if value["skills"]["upstream_typesafe_sha256"] != agentic_jev_skill_sha256():
        raise WorkflowError("decision-skill v3 upstream TypeSafe skill changed")
    if value["skills"]["decision_support_sha256"] != decision_skill_sha256():
        raise WorkflowError("decision-skill v3 decision support skill changed")
    if (
        value["skills"]["decision_support_interface_sha256"]
        != decision_skill_interface_sha256()
    ):
        raise WorkflowError("decision-skill v3 interface metadata changed")
    if value["host_tool"]["implementation_sha256"] != runtime["host_tool"]["implementation_sha256"]:
        raise WorkflowError("decision-skill v3 host tool changed")
    return value, runtime


def build_decision_v3_solver(
    *,
    runtime: Mapping[str, Any],
    receipt_path: Path,
) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError("decision-skill v3 requires Agentic-Jev dependencies") from exc

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
        raise WorkflowError("decision-skill v3 qualification requires Inspect AI") from exc

    from .inspect_adjudication import _inspect_sandbox_spec

    root = output_root / arm
    root.mkdir(parents=True, exist_ok=False)
    receipt_path = root / "jev-tool-receipts.jsonl"

    if arm == "v2-control":
        solver = build_decision_v2_solver(runtime=runtime, receipt_path=receipt_path)
    elif arm == "v3-treatment":
        solver = build_decision_v3_solver(runtime=runtime, receipt_path=receipt_path)
    else:
        raise WorkflowError(f"unknown v3 qualification arm: {arm}")

    task = Task(
        dataset=[
            Sample(
                id=f"decision-skill-v3-activation-{arm}",
                input=_ACTIVATION_PROMPT,
                files={"README.md": "Synthetic second-order decision fixture.\n"},
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
        raise WorkflowError(f"v3 activation arm {arm} produced no log")
    log = logs[0]
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1 or getattr(samples[0], "error", None):
        raise WorkflowError(f"v3 activation arm {arm} failed")

    receipts = _receipt_values(receipt_path)
    successful = [item for item in receipts if item.get("status") == "success"]
    summary = _receipt_summary(receipt_path)
    return {
        "arm": arm,
        "inspect_log": getattr(log, "location", None),
        "outer_tool_functions": _tool_call_functions(log),
        "jev_tool_calls": len(receipts),
        "successful_jev_calls": len(successful),
        "receipt_summary": summary,
        "second_order_primitives": (
            int(summary["primitive_counts"]["noul"])
            + int(summary["primitive_counts"]["score"])
        ),
        "api_key_absent_from_transcript": not _transcript_contains_secret(log),
    }


def run_decision_v3_activation_qualification(
    *,
    output_root: Path,
    v3_lock_path: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "decision-skill v3 qualification root is not empty; preserve prior attempt"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    _, runtime = load_decision_v3_lock(v3_lock_path)
    lowered = _ACTIVATION_PROMPT.lower()
    if "jev" in lowered or "typesafe" in lowered:
        raise WorkflowError("v3 activation prompt must not name Jev or TypeSafe")

    control = _run_activation_arm(
        arm="v2-control",
        output_root=output_root,
        runtime=runtime,
    )
    treatment = _run_activation_arm(
        arm="v3-treatment",
        output_root=output_root,
        runtime=runtime,
    )

    qualified = (
        control["jev_tool_calls"] == 0
        and treatment["jev_tool_calls"] == 1
        and treatment["successful_jev_calls"] == 1
        and treatment["second_order_primitives"] >= 1
        and treatment["api_key_absent_from_transcript"] is True
    )
    record = {
        "schema": QUAL_SCHEMA,
        "study_id": STUDY_ID,
        "qualified": qualified,
        "v3_lock_sha256": sha256_file(v3_lock_path),
        "activation_protocol": {
            "id": ACTIVATION_PROTOCOL_ID,
            "sha256": activation_protocol_sha256(),
            "proposal_deterministically_resolved": "proposal_2",
            "remaining_semantic_questions": [
                "evidence sufficiency",
                "qualitative implementation risk",
            ],
        },
        "control": control,
        "treatment": treatment,
        "activation_lift_observed": (
            control["jev_tool_calls"] == 0 and treatment["jev_tool_calls"] == 1
        ),
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "qualification_only_tests_second_order_activation": True,
        },
    }
    validate_instance(record, QUAL_SCHEMA, artifact="decision-skill v3 qualification")
    result_path = output_root / "qualification.json"
    atomic_write_json(result_path, record)
    if not qualified:
        raise WorkflowError(
            "decision-skill v3 activation qualification failed; inspect qualification.json"
        )
    return {"path": str(result_path), **record}


def _run_manager_sample(
    *,
    sample_id: str,
    sample_root: Path,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_evals.swe_lancer import swe_lancer
    except ImportError as exc:
        raise WorkflowError("decision-skill v3 canary requires Inspect Evals") from exc

    receipt_path = sample_root / "jev-tool-receipts.jsonl"
    solver = build_decision_v3_solver(runtime=runtime, receipt_path=receipt_path)
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
        raise WorkflowError(f"v3 manager sample {sample_id} produced no log")
    log = logs[0]
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1:
        raise WorkflowError(
            f"v3 manager sample {sample_id} expected one sample; observed {len(samples)}"
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


def run_decision_v3_manager_canary(
    *,
    output_root: Path,
    v3_lock_path: Path,
    activation_qualification_path: Path,
    inspect_evals_checkout: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError("decision-skill v3 canary root is not empty")
    output_root.mkdir(parents=True, exist_ok=True)

    lock, runtime = load_decision_v3_lock(v3_lock_path)
    qualification = _read_json_object(activation_qualification_path)
    validate_instance(qualification, QUAL_SCHEMA, artifact=str(activation_qualification_path))
    if qualification.get("qualified") is not True:
        raise WorkflowError("decision-skill v3 qualification is not passing")
    if qualification.get("v3_lock_sha256") != sha256_file(v3_lock_path):
        raise WorkflowError("decision-skill v3 qualification used another lock")
    protocol = qualification.get("activation_protocol")
    if not isinstance(protocol, Mapping):
        raise WorkflowError("decision-skill v3 qualification has no protocol")
    if protocol.get("id") != ACTIVATION_PROTOCOL_ID:
        raise WorkflowError("decision-skill v3 qualification protocol mismatch")
    if protocol.get("sha256") != activation_protocol_sha256():
        raise WorkflowError("decision-skill v3 qualification protocol hash changed")

    cohort_path = Path(str(lock["external_cohort"]["path"]))
    cohort = _load_external_cohort(cohort_path)
    checkout = Path(inspect_evals_checkout)
    _require_external_sources(checkout, cohort)
    _activate_pinned_inspect_evals(checkout)

    manager = cohort["cohorts"]["swe_lancer_manager_choice"]
    selected = manager[:CANARY_COUNT]
    samples: list[dict[str, Any]] = []
    for entry in selected:
        sample_id = str(entry["id"])
        sample_root = output_root / sample_id
        sample_root.mkdir(parents=True, exist_ok=False)
        result = _run_manager_sample(
            sample_id=sample_id,
            sample_root=sample_root,
            runtime=runtime,
        )
        atomic_write_json(sample_root / "sample-result.json", result)
        samples.append(result)

    calls = sum(int(item["jev_tool_calls"]) for item in samples)
    called_ids = [str(item["sample_id"]) for item in samples if item["jev_tool_calls"] > 0]
    success = sum(int(item["sample_status"]["success"]) for item in samples)
    errors = sum(int(item["sample_status"]["error"]) for item in samples)
    record = {
        "schema": CANARY_SCHEMA,
        "study_id": STUDY_ID,
        "development_only": True,
        "v3_lock_sha256": sha256_file(v3_lock_path),
        "activation_qualification_sha256": sha256_file(activation_qualification_path),
        "execution": {
            "arm": "decision-skill-v3",
            "source": "swe_lancer_manager_choice",
            "sample_selection": "first-two-frozen-manager-ids",
            "samples_expected": CANARY_COUNT,
            "samples_observed": len(samples),
            "success": success,
            "errors": errors,
            "jev_tool_calls": calls,
            "samples_with_jev_calls": called_ids,
            "scoring_enabled": False,
        },
        "samples": samples,
        "gate": {
            "passed": calls > 0 and errors == 0,
            "requirement": "at least one authoritative host-tool Jev receipt across canary",
            "next": (
                "design remaining-manager expansion"
                if calls > 0 and errors == 0
                else "stop; inspect canary decision traces before any further manager spend"
            ),
        },
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
        },
    }
    validate_instance(record, CANARY_SCHEMA, artifact="decision-skill v3 manager canary")
    result_path = output_root / "run-manifest.json"
    atomic_write_json(result_path, record)
    if record["gate"]["passed"] is not True:
        raise WorkflowError(
            "decision-skill v3 manager canary produced no live-Jev uptake; "
            "inspect preserved canary evidence before continuing"
        )
    return {"path": str(result_path), **record}
