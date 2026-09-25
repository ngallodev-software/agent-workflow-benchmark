from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError

from .schema_contracts import read_contract

ABC_ADJUDICATION_MODULE_SCHEMA = (
    "agent-workflow-benchmark/abc-adjudication-module/v1"
)


def _stable_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_relative_safe(path: str, *, field: str) -> None:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        raise WorkflowError(f"{field} must be a safe relative path: {path!r}")


def validate_abc_adjudication_module(path: Path) -> dict[str, Any]:
    source = Path(path)
    value = read_contract(source, ABC_ADJUDICATION_MODULE_SCHEMA)

    primary = value["roles"]["primary"]
    roles = [str(item["role"]) for item in primary]
    if set(roles) != {"A", "B"} or len(roles) != 2:
        raise WorkflowError(
            "A/B/C adjudication module must define exactly primary roles A and B"
        )

    tiebreaker = value["roles"]["tiebreaker"]
    adjudicator_ids = [
        str(primary[0]["adjudicator_id"]),
        str(primary[1]["adjudicator_id"]),
        str(tiebreaker["adjudicator_id"]),
    ]
    if len(set(adjudicator_ids)) != 3:
        raise WorkflowError("A, B, and C adjudicator_id values must be distinct")

    result_subdirs = [
        str(primary[0]["result_subdir"]),
        str(primary[1]["result_subdir"]),
        str(tiebreaker["result_subdir"]),
    ]
    if len(set(result_subdirs)) != 3:
        raise WorkflowError("A, B, and C result_subdir values must be distinct")
    for index, result_subdir in enumerate(result_subdirs):
        _require_relative_safe(
            result_subdir,
            field=f"roles result_subdir[{index}]",
        )

    required_files = value["required_files"]
    ids = [str(item["id"]) for item in required_files]
    if len(ids) != len(set(ids)):
        raise WorkflowError("required_files IDs must be unique")

    targets_by_role: dict[str, set[str]] = {
        "A": set(),
        "B": set(),
        "C": set(),
        "coordinator": set(),
    }
    shared_frozen_ab: list[str] = []
    for item in required_files:
        source_path = str(item["source_path"])
        _require_relative_safe(source_path, field=f"required_files[{item['id']}].source_path")
        target = str(item["target"])
        roles_for_file = {str(role) for role in item["roles"]}
        if {"A", "B"}.issubset(roles_for_file) and item.get("sha256"):
            shared_frozen_ab.append(str(item["id"]))
        for role in roles_for_file:
            if target in targets_by_role[role]:
                raise WorkflowError(
                    f"duplicate target {target!r} for role {role}"
                )
            targets_by_role[role].add(target)

    if not shared_frozen_ab:
        raise WorkflowError(
            "A/B/C adjudication module must provide at least one hash-pinned "
            "input shared by both A and B"
        )

    prompt = value["prompt"]
    _require_relative_safe(str(prompt["template"]), field="prompt.template")

    runtime = value["runtime"]
    _require_relative_safe(str(runtime["dockerfile"]), field="runtime.dockerfile")

    results = value["results"]
    for field in (
        "runtime_root",
        "coordinator_subdir",
        "frozen_result",
        "freeze_manifest",
        "final_validation",
    ):
        _require_relative_safe(str(results[field]), field=f"results.{field}")

    guardrails = value["guardrails"]
    if guardrails["cross_agent_visibility"] is not False:
        raise WorkflowError("cross-agent visibility must remain disabled")
    if guardrails["other_adjudicator_labels_visible"] is not False:
        raise WorkflowError("prior adjudicator labels must remain hidden")
    if guardrails["treatment_outputs_visible"] is not False:
        raise WorkflowError("treatment outputs must remain hidden")

    coordination = value["coordination"]
    if coordination["reveal_policy"] != "after-all-primary-complete":
        raise WorkflowError("A/B outputs may be revealed only after both primary runs complete")
    module_sha256 = _stable_sha256(value)
    return {
        "valid": True,
        "path": str(source),
        "schema": value["schema"],
        "module_id": value["module_id"],
        "module_version": value["module_version"],
        "study_id": value["task"]["study_id"],
        "dataset_version": value["task"]["dataset_version"],
        "protocol_version": value["task"]["protocol_version"],
        "module_sha256": module_sha256,
        "primary_roles": roles,
        "adjudicator_ids": adjudicator_ids,
        "shared_frozen_ab_inputs": sorted(shared_frozen_ab),
        "required_files": len(required_files),
        "guardrails": {
            "repository_mounted": guardrails["repository_mounted"],
            "docker_socket_mounted": guardrails["docker_socket_mounted"],
            "root_filesystem_read_only": guardrails["root_filesystem_read_only"],
            "cross_agent_visibility": guardrails["cross_agent_visibility"],
            "treatment_outputs_visible": guardrails["treatment_outputs_visible"],
        },
    }
