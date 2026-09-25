from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence

import agent_workflow_comparative_eval as comparative
from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .adjudication_module import validate_abc_adjudication_module
from .schema_contracts import validate_instance
from .oracle_adjudication import (
    ADJUDICATION_PASS_SCHEMA,
    _decision_specs,
    _load_view,
    _study_spec,
    _validate_label,
    export_oracle_dispute_view,
    freeze_oracle_bundle,
    validate_adjudication_pass,
)

INSPECT_AI_VERSION = "0.3.268"
INSPECT_SWE_VERSION = "0.2.70"
CODEX_VERSION_POLICY = "latest-at-cohort-start"
RUNTIME_LOCK_SCHEMA = "agent-workflow-benchmark/adjudication-runtime-lock/v1"
INSPECT_QUALIFICATION_SCHEMA = (
    "agent-workflow-benchmark/inspect-adjudication-qualification/v1"
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _require_inspect_dependencies() -> tuple[Any, Any]:
    inspect_version = _package_version("inspect-ai")
    inspect_swe_version = _package_version("inspect-swe")
    missing = [
        name
        for name, version in (
            ("inspect-ai", inspect_version),
            ("inspect-swe", inspect_swe_version),
        )
        if version is None
    ]
    if missing:
        raise WorkflowError(
            "Inspect adjudication runtime is not installed; install "
            "'agent-workflow-benchmark[inspect]'. Missing: "
            + ", ".join(missing)
        )
    if inspect_version != INSPECT_AI_VERSION:
        raise WorkflowError(
            f"Inspect AI runtime mismatch: expected {INSPECT_AI_VERSION}, "
            f"found {inspect_version}"
        )
    if inspect_swe_version != INSPECT_SWE_VERSION:
        raise WorkflowError(
            f"Inspect SWE runtime mismatch: expected {INSPECT_SWE_VERSION}, "
            f"found {inspect_swe_version}"
        )
    try:
        import inspect_ai
        import inspect_swe
    except ImportError as exc:
        raise WorkflowError(f"unable to import Inspect adjudication runtime: {exc}") from exc
    return inspect_ai, inspect_swe


def _sandbox_platform() -> str:
    if platform.system().lower() != "linux":
        raise WorkflowError("Inspect adjudication qualification currently requires Linux")
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if machine in {"aarch64", "arm64"}:
        return "linux-arm64"
    raise WorkflowError(f"unsupported Inspect adjudication architecture: {machine}")


def _version_key(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"(\d+(?:\.\d+)*)", value.strip())
    if not match:
        return ()
    return tuple(int(item) for item in match.group(1).split("."))


def resolve_latest_codex_cli() -> dict[str, str]:
    _, inspect_swe = _require_inspect_dependencies()
    target = _sandbox_platform()
    try:
        inspect_swe.download_agent_binary("codex_cli", "latest", target)
        cached = inspect_swe.cached_agent_binaries("codex_cli", quiet=True)
    except Exception as exc:
        raise WorkflowError(f"failed to resolve latest Codex CLI via Inspect SWE: {exc}") from exc

    binaries = [
        item
        for item in cached
        if getattr(item, "agent", None) == "codex_cli"
        and _version_key(str(getattr(item, "version", "")))
    ]
    if not binaries:
        raise WorkflowError("Inspect SWE did not expose a cached Codex CLI after download")
    selected = max(binaries, key=lambda item: _version_key(str(item.version)))
    return {
        "policy": CODEX_VERSION_POLICY,
        "requested": "latest",
        "resolved": str(selected.version),
        "platform": target,
        "cached_path": str(selected.path),
    }


def _run_version_command(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError(f"runtime dependency check failed for {' '.join(command)}: {exc}") from exc
    return (result.stdout or result.stderr).strip()


def _docker_identity() -> dict[str, str]:
    return {
        "docker": _run_version_command(["docker", "--version"]),
        "compose": _run_version_command(["docker", "compose", "version"]),
    }


def create_inspect_runtime_lock(
    module_path: Path,
    destination: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    module = validate_abc_adjudication_module(Path(module_path))
    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"adjudication runtime lock already exists: {destination}")
    if destination.exists() and (destination.is_dir() or destination.is_symlink()):
        raise WorkflowError(f"adjudication runtime lock must be a regular file: {destination}")

    _require_inspect_dependencies()
    codex = resolve_latest_codex_cli()
    docker = _docker_identity()
    record = {
        "schema": RUNTIME_LOCK_SCHEMA,
        "created_at": _utc(),
        "module_id": module["module_id"],
        "module_version": module["module_version"],
        "module_sha256": module["module_sha256"],
        "backend": "inspect-ai",
        "inspect_ai_version": INSPECT_AI_VERSION,
        "inspect_swe_version": INSPECT_SWE_VERSION,
        "codex_cli": codex,
        "docker": docker,
        "frozen_for_cohort": True,
    }
    validate_instance(record, RUNTIME_LOCK_SCHEMA, artifact="adjudication runtime lock")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        **record,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"JSON artifact must be an object: {path}")
    return value


def _load_runtime_lock(path: Path, module: Mapping[str, Any]) -> dict[str, Any]:
    value = _read_json(path)
    validate_instance(value, RUNTIME_LOCK_SCHEMA, artifact=str(path))
    if value.get("schema") != RUNTIME_LOCK_SCHEMA:
        raise WorkflowError(f"unsupported adjudication runtime lock schema: {value.get('schema')!r}")
    if value.get("backend") != "inspect-ai":
        raise WorkflowError("adjudication runtime lock is not for Inspect AI")
    if value.get("module_id") != module["module_id"]:
        raise WorkflowError("runtime lock module_id does not match adjudication module")
    if value.get("module_sha256") != module["module_sha256"]:
        raise WorkflowError("runtime lock module_sha256 does not match adjudication module")
    codex = value.get("codex_cli")
    if not isinstance(codex, Mapping) or not codex.get("resolved"):
        raise WorkflowError("runtime lock has no resolved Codex CLI cohort version")
    if value.get("inspect_ai_version") != INSPECT_AI_VERSION:
        raise WorkflowError("runtime lock Inspect AI version does not match installed policy")
    if value.get("inspect_swe_version") != INSPECT_SWE_VERSION:
        raise WorkflowError("runtime lock Inspect SWE version does not match installed policy")
    return value


def _require_passing_qualification(
    qualification_path: Path | None,
    *,
    module: Mapping[str, Any],
    runtime_lock_path: Path,
    allow_unqualified: bool,
) -> None:
    if allow_unqualified:
        return
    if qualification_path is None:
        raise WorkflowError(
            "real Inspect adjudication requires a passing P0A qualification manifest"
        )
    value = _read_json(Path(qualification_path))
    validate_instance(
        value,
        INSPECT_QUALIFICATION_SCHEMA,
        artifact=str(qualification_path),
    )
    if value.get("qualified") is not True:
        raise WorkflowError("Inspect adjudication qualification is not passing")
    if value.get("module_id") != module["module_id"]:
        raise WorkflowError("qualification module_id does not match adjudication module")
    if value.get("module_sha256") != module["module_sha256"]:
        raise WorkflowError("qualification module_sha256 does not match adjudication module")
    if value.get("runtime_lock_sha256") != sha256_file(Path(runtime_lock_path)):
        raise WorkflowError(
            "qualification runtime_lock_sha256 does not match supplied runtime lock"
        )
    if any(
        gate.get("status") != "pass"
        for gate in value.get("gates", {}).values()
        if isinstance(gate, Mapping)
    ):
        raise WorkflowError("Inspect adjudication qualification contains a non-passing gate")


def _repo_root(module_path: Path) -> Path:
    current = Path(module_path).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "agent_workflow_benchmark"
        ).is_dir():
            return candidate
    raise WorkflowError(f"unable to locate benchmark repository root from {module_path}")


def _render_prompt(template_path: Path, adjudicator_id: str) -> str:
    try:
        template = Path(template_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"unable to read adjudicator prompt template {template_path}: {exc}") from exc
    return template.replace("{{ADJUDICATOR_ID}}", adjudicator_id)


def _json_completion(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            raw = "\n".join(lines[1:-1])
            if raw.lstrip().lower().startswith("json\n"):
                raw = raw.lstrip()[5:]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Inspect adjudicator did not return a JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError("Inspect adjudicator output must be a JSON object")
    return value


def _wrap_pass(
    view_path: Path,
    output: Mapping[str, Any],
    *,
    adjudicator_id: str,
    study: str,
) -> dict[str, Any]:
    view, expected, view_sha256 = _load_view(Path(view_path), study=study)
    spec = _study_spec(study)
    decisions = _decision_specs(spec)
    records = output.get("records")
    if not isinstance(records, list):
        raise WorkflowError("Inspect adjudicator output must contain a records array")

    by_case: dict[str, Mapping[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise WorkflowError("Inspect adjudicator records must be objects")
        case_id = str(raw.get("case_id") or "")
        if not case_id or case_id in by_case:
            raise WorkflowError(f"invalid or duplicate Inspect adjudication case ID: {case_id!r}")
        labels = raw.get("labels")
        if not isinstance(labels, Mapping):
            raise WorkflowError(f"Inspect adjudication labels for {case_id} must be an object")
        wanted = expected.get(case_id)
        if wanted is None or set(labels) != wanted:
            raise WorkflowError(
                f"Inspect adjudication labels for {case_id} do not match required seams"
            )
        for decision_id, label in labels.items():
            _validate_label(str(decision_id), label, decisions=decisions)
        by_case[case_id] = {"case_id": case_id, "labels": dict(labels)}

    if set(by_case) != set(expected):
        missing = sorted(set(expected) - set(by_case))
        extra = sorted(set(by_case) - set(expected))
        raise WorkflowError(
            f"Inspect adjudication case set mismatch; missing={missing}, extra={extra}"
        )

    return {
        "schema": ADJUDICATION_PASS_SCHEMA,
        "study_id": view["study_id"],
        "dataset_version": view["dataset_version"],
        "protocol_version": spec["oracle_policy"]["protocol_version"],
        "input_view_sha256": view_sha256,
        "adjudicator_id": adjudicator_id,
        "completed_at": _utc(),
        "attestation": {
            "independent": True,
            "treatment_outputs_seen": False,
            "other_adjudicator_labels_seen": False,
        },
        "records": [by_case[case_id] for case_id in expected],
    }


@dataclass(frozen=True)
class InspectRunConfig:
    module_path: Path
    view_path: Path
    protocol_path: Path
    runtime_lock_path: Path
    output_root: Path
    model: str
    qualification_path: Path | None = None
    model_args: Mapping[str, Any] | None = None
    log_model_api: bool = False
    allow_unqualified: bool = False


def _inspect_sandbox_spec() -> Any:
    from inspect_ai.util import ComposeConfig, ComposeService, SandboxEnvironmentSpec

    service = ComposeService(
        image="python:3.12-bookworm",
        init=True,
        command="tail -f /dev/null",
        network_mode="none",
        mem_limit="1g",
        cpus=1.0,
        read_only=True,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        working_dir="/workspace",
        tmpfs=[
            "/workspace:exec,mode=1777",
            "/tmp:exec,mode=1777",
            "/var/tmp:exec,mode=1777",
            "/root/.codex:exec,mode=0700",
        ],
    )
    return SandboxEnvironmentSpec("docker", ComposeConfig(services={"default": service}))


def _inspect_eval(
    *,
    samples: list[Any],
    codex_version: str,
    model: str,
    model_args: Mapping[str, Any] | None,
    log_dir: Path,
    max_samples: int,
    log_model_api: bool,
) -> Any:
    inspect_ai, inspect_swe = _require_inspect_dependencies()
    from inspect_ai import Task
    from inspect_swe import codex_cli

    solver = codex_cli(
        version=codex_version,
        web_search="disabled",
        goals=False,
        attempts=1,
        mcp_servers=[],
        bridged_tools=[],
        auto_review=False,
        home_dir="/tmp/codex-home",
        config_overrides={
            "approval_policy": "never",
            "web_search": "disabled",
        },
    )
    task = Task(
        dataset=samples,
        solver=solver,
        sandbox=_inspect_sandbox_spec(),
        checkpoint=False,
    )
    logs = inspect_ai.eval(
        task,
        model=model,
        model_args=dict(model_args or {}),
        log_dir=str(log_dir),
        log_format="eval",
        max_samples=max_samples,
        max_sandboxes=max_samples,
        max_subprocesses=max(2, max_samples),
        fail_on_error=True,
        retry_on_error=0,
        score=False,
        log_model_api=log_model_api,
        display="plain",
    )
    if len(logs) != 1:
        raise WorkflowError(f"Inspect adjudication expected one task log, got {len(logs)}")
    log = logs[0]
    if getattr(log, "status", None) != "success":
        error = getattr(log, "error", None)
        raise WorkflowError(f"Inspect adjudication task failed: {error}")
    if not getattr(log, "samples", None):
        raise WorkflowError("Inspect adjudication task returned no samples")
    return log


def _sample_files(view_path: Path, protocol_path: Path) -> dict[str, str]:
    return {
        "oracle-view.json": str(Path(view_path).resolve()),
        "oracle-protocol.md": str(Path(protocol_path).resolve()),
    }


def run_inspect_primary(config: InspectRunConfig) -> dict[str, Any]:
    module = validate_abc_adjudication_module(config.module_path)
    runtime_lock = _load_runtime_lock(config.runtime_lock_path, module)
    _require_passing_qualification(
        config.qualification_path,
        module=module,
        runtime_lock_path=config.runtime_lock_path,
        allow_unqualified=config.allow_unqualified,
    )
    repo = _repo_root(config.module_path)
    module_value = _read_json(config.module_path)
    template = repo / str(module_value["prompt"]["template"])
    primary = module_value["roles"]["primary"]

    from inspect_ai.dataset import Sample

    samples = [
        Sample(
            id=str(item["role"]),
            input=_render_prompt(template, str(item["adjudicator_id"])),
            files=_sample_files(config.view_path, config.protocol_path),
            metadata={
                "role": str(item["role"]),
                "adjudicator_id": str(item["adjudicator_id"]),
                "input_view_sha256": sha256_file(config.view_path),
            },
        )
        for item in primary
    ]

    config.output_root.mkdir(parents=True, exist_ok=True)
    log_dir = config.output_root / "inspect-logs" / "primary"
    log = _inspect_eval(
        samples=samples,
        codex_version=str(runtime_lock["codex_cli"]["resolved"]),
        model=config.model,
        model_args=config.model_args,
        log_dir=log_dir,
        max_samples=2,
        log_model_api=config.log_model_api,
    )

    by_id = {str(sample.id): sample for sample in log.samples or []}
    if set(by_id) != {"A", "B"}:
        raise WorkflowError(f"Inspect primary sample set mismatch: {sorted(by_id)}")

    outputs: dict[str, Any] = {}
    for item in primary:
        role = str(item["role"])
        adjudicator_id = str(item["adjudicator_id"])
        sample = by_id[role]
        if sample.error:
            raise WorkflowError(f"Inspect adjudicator {role} failed: {sample.error}")
        completion = getattr(sample.output, "completion", "")
        result = _json_completion(completion)
        contract = _wrap_pass(
            config.view_path,
            result,
            adjudicator_id=adjudicator_id,
            study=str(module_value["task"]["study_id"]),
        )
        role_spec = next(item for item in primary if str(item["role"]) == role)
        role_dir = config.output_root / str(role_spec["result_subdir"])
        role_dir.mkdir(parents=True, exist_ok=True)
        pass_path = role_dir / "adjudication.json"
        if pass_path.exists():
            raise WorkflowError(f"Inspect adjudication result already exists: {pass_path}")
        atomic_write_json(pass_path, contract)
        provenance = {
            "backend": "inspect-ai",
            "role": role,
            "adjudicator_id": adjudicator_id,
            "runtime_lock_sha256": sha256_file(config.runtime_lock_path),
            "inspect_eval_id": log.eval.eval_id,
            "inspect_run_id": log.eval.run_id,
            "inspect_log": log.location,
            "sample_uuid": sample.uuid,
            "sample_retries": sample.retries,
            "sample_total_time": sample.total_time,
            "sample_working_time": sample.working_time,
            "model": getattr(sample.output, "model", None),
            "model_usage": (
                sample.output.usage.model_dump(mode="json")
                if getattr(sample.output, "usage", None) is not None
                else None
            ),
            "pass_sha256": sha256_file(pass_path),
        }
        atomic_write_json(role_dir / "inspect-provenance.json", provenance)
        outputs[role] = {
            "path": str(pass_path),
            "sha256": provenance["pass_sha256"],
            "provenance": str(role_dir / "inspect-provenance.json"),
        }

    manifest = {
        "backend": "inspect-ai",
        "kind": "primary",
        "completed_at": _utc(),
        "runtime_lock": str(config.runtime_lock_path),
        "runtime_lock_sha256": sha256_file(config.runtime_lock_path),
        "view_sha256": sha256_file(config.view_path),
        "model": config.model,
        "outputs": outputs,
        "reveal_policy": "after-all-primary-complete",
    }
    atomic_write_json(config.output_root / "primary-run-manifest.json", manifest)
    return manifest


def run_inspect_tiebreaker(config: InspectRunConfig) -> dict[str, Any]:
    module = validate_abc_adjudication_module(config.module_path)
    runtime_lock = _load_runtime_lock(config.runtime_lock_path, module)
    _require_passing_qualification(
        config.qualification_path,
        module=module,
        runtime_lock_path=config.runtime_lock_path,
        allow_unqualified=config.allow_unqualified,
    )
    repo = _repo_root(config.module_path)
    module_value = _read_json(config.module_path)
    template = repo / str(module_value["prompt"]["template"])
    tiebreaker = module_value["roles"]["tiebreaker"]
    adjudicator_id = str(tiebreaker["adjudicator_id"])

    from inspect_ai.dataset import Sample

    sample = Sample(
        id="C",
        input=_render_prompt(template, adjudicator_id),
        files=_sample_files(config.view_path, config.protocol_path),
        metadata={
            "role": "C",
            "adjudicator_id": adjudicator_id,
            "input_view_sha256": sha256_file(config.view_path),
        },
    )
    config.output_root.mkdir(parents=True, exist_ok=True)
    log = _inspect_eval(
        samples=[sample],
        codex_version=str(runtime_lock["codex_cli"]["resolved"]),
        model=config.model,
        model_args=config.model_args,
        log_dir=config.output_root / "inspect-logs" / "tiebreaker",
        max_samples=1,
        log_model_api=config.log_model_api,
    )
    result_sample = (log.samples or [None])[0]
    if result_sample is None or result_sample.error:
        raise WorkflowError(
            f"Inspect adjudicator C failed: {getattr(result_sample, 'error', None)}"
        )
    contract = _wrap_pass(
        config.view_path,
        _json_completion(getattr(result_sample.output, "completion", "")),
        adjudicator_id=adjudicator_id,
        study=str(module_value["task"]["study_id"]),
    )
    role_dir = config.output_root / str(tiebreaker["result_subdir"])
    role_dir.mkdir(parents=True, exist_ok=True)
    pass_path = role_dir / "adjudication.json"
    if pass_path.exists():
        raise WorkflowError(f"Inspect adjudication result already exists: {pass_path}")
    atomic_write_json(pass_path, contract)
    provenance = {
        "backend": "inspect-ai",
        "role": "C",
        "adjudicator_id": adjudicator_id,
        "runtime_lock_sha256": sha256_file(config.runtime_lock_path),
        "inspect_eval_id": log.eval.eval_id,
        "inspect_run_id": log.eval.run_id,
        "inspect_log": log.location,
        "sample_uuid": result_sample.uuid,
        "sample_retries": result_sample.retries,
        "sample_total_time": result_sample.total_time,
        "sample_working_time": result_sample.working_time,
        "model": getattr(result_sample.output, "model", None),
        "model_usage": (
            result_sample.output.usage.model_dump(mode="json")
            if getattr(result_sample.output, "usage", None) is not None
            else None
        ),
        "pass_sha256": sha256_file(pass_path),
    }
    atomic_write_json(role_dir / "inspect-provenance.json", provenance)
    return {
        "backend": "inspect-ai",
        "kind": "tiebreaker",
        "completed_at": _utc(),
        "path": str(pass_path),
        "sha256": provenance["pass_sha256"],
        "provenance": str(role_dir / "inspect-provenance.json"),
    }



def _synthetic_qualification_view(destination: Path) -> dict[str, Any]:
    spec = _study_spec("routing-semantic-v1")
    eligible = {
        str(item["decision_id"]): True
        for item in spec["decision_seams"]
        if isinstance(item, Mapping)
    }
    record = {
        "schema": comparative.ORACLE_AUTHORING_VIEW_SCHEMA,
        "study_id": spec["study_id"],
        "dataset_version": "routing-semantic-corpus-v1.0.0",
        "decision_seams": copy.deepcopy(spec["decision_seams"]),
        "oracle_policy": copy.deepcopy(spec["oracle_policy"]),
        "cases": [
            {
                "case_id": "inspect-qualification-001",
                "task": (
                    "Create a local development README note explaining how to run "
                    "a synthetic example. Do not publish anything."
                ),
                "metadata": {
                    "environment": "development",
                    "requirements_state": "complete",
                    "requires_interaction": False,
                    "risk": "low",
                    "task_type": "documentation",
                },
                "oracle_eligible": dict(eligible),
            },
            {
                "case_id": "inspect-qualification-002",
                "task": (
                    "Review a proposed production database deletion and identify "
                    "whether explicit user authorization is required before execution."
                ),
                "metadata": {
                    "environment": "production",
                    "requirements_state": "complete",
                    "requires_interaction": True,
                    "risk": "high",
                    "task_type": "review",
                },
                "oracle_eligible": dict(eligible),
            },
        ],
        "blinding": {
            "construction_tags_included": False,
            "control_outputs_included": False,
            "candidate_outputs_included": False,
        },
    }
    try:
        comparative.validate_record(record, comparative.ORACLE_AUTHORING_VIEW_SCHEMA)
    except comparative.ContractError as exc:
        raise WorkflowError(f"synthetic qualification view is invalid: {exc}") from exc
    atomic_write_json(destination, record)
    return record


def _synthetic_protocol(destination: Path) -> None:
    destination.write_text(
        """# Synthetic Inspect adjudication qualification protocol

This file exists only to qualify the isolated adjudicator runtime. It does not
contain or alter any real routing-semantic-v1 oracle labels.

Apply the same frozen label domains used by routing-semantic-v1:

- routing.task_class: implementation, diagnosis, review, documentation, other.
- routing.interaction_required: true only when a material user decision,
  authorization, or preference is required before responsible completion.
- routing.semantic_risk: 0 low/reversible, 1 moderate/recoverable, 2 high
  production/security/authorization/destructive/public/financial consequence.

For mixed task-class intent, implementation wins when executable change is
explicitly required; otherwise review, then diagnosis, then documentation,
then other. Declared metadata is evidence, not ground truth.
""",
        encoding="utf-8",
    )


def _host_secret_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if not value:
            continue
        if (
            upper.startswith("TYPESAFE_")
            or upper.endswith("_API_KEY")
            or upper.endswith("_TOKEN")
            or upper.endswith("_SECRET")
            or upper in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
        ):
            result[name] = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return result


def _run_guardrail_probe(
    *,
    output_root: Path,
    model: str,
    model_args: Mapping[str, Any] | None,
) -> dict[str, Any]:
    inspect_ai, _ = _require_inspect_dependencies()
    from inspect_ai import Task
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelOutput
    from inspect_ai.solver import Generate, Solver, TaskState, solver
    from inspect_ai.util import sandbox

    secret_hashes = _host_secret_hashes()
    embedded_hashes = json.dumps(secret_hashes, sort_keys=True)

    @solver
    def guardrail_probe() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            code = r'''
import hashlib
import json
import os
from pathlib import Path
import socket

host_hashes = json.loads(%r)
matched = []
for name, expected in host_hashes.items():
    value = os.environ.get(name)
    if value is not None:
        actual = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if actual == expected:
            matched.append(name)

network_reachable = False
try:
    connection = socket.create_connection(("1.1.1.1", 443), timeout=0.5)
    connection.close()
    network_reachable = True
except Exception:
    pass

workspace = Path("/workspace")
visible_files = []
if workspace.exists():
    for path in workspace.rglob("*"):
        if path.is_file():
            visible_files.append(str(path.relative_to(workspace)))

report = {
    "matched_host_secret_names": sorted(matched),
    "typesafe_env_names": sorted(
        name for name in os.environ if name.upper().startswith("TYPESAFE_")
    ),
    "docker_socket_present": Path("/var/run/docker.sock").exists(),
    "workspace_git_present": (workspace / ".git").exists(),
    "repo_git_present": Path("/repo/.git").exists(),
    "external_network_reachable": network_reachable,
    "visible_workspace_files": sorted(visible_files),
}
print(json.dumps(report, sort_keys=True))
''' % embedded_hashes
            result = await sandbox().exec(
                ["python", "-c", code],
                cwd="/workspace",
                timeout=30,
            )
            if not result.success:
                raise RuntimeError(
                    f"guardrail probe failed: {result.stderr or result.stdout}"
                )
            state.output = ModelOutput.from_content(
                "guardrail-probe",
                result.stdout.strip(),
            )
            return state

        return solve

    output_root.mkdir(parents=True, exist_ok=True)
    task = Task(
        dataset=[
            Sample(
                id="guardrail",
                input="Run the deterministic sandbox guardrail probe.",
                files={"allowed.txt": "qualification sentinel\n"},
            )
        ],
        solver=guardrail_probe(),
        sandbox=_inspect_sandbox_spec(),
        checkpoint=False,
    )
    logs = inspect_ai.eval(
        task,
        model=model,
        model_args=dict(model_args or {}),
        log_dir=str(output_root / "inspect-logs" / "guardrail"),
        log_format="eval",
        max_samples=1,
        max_sandboxes=1,
        retry_on_error=0,
        score=False,
        display="plain",
    )
    if len(logs) != 1 or getattr(logs[0], "status", None) != "success":
        raise WorkflowError("Inspect guardrail probe did not complete successfully")
    samples = logs[0].samples or []
    if len(samples) != 1 or samples[0].error:
        raise WorkflowError(
            f"Inspect guardrail probe sample failed: "
            f"{getattr(samples[0] if samples else None, 'error', None)}"
        )
    report = _json_completion(samples[0].output.completion)
    expected_files = {"allowed.txt"}
    actual_files = set(report.get("visible_workspace_files") or [])
    passed = (
        not report.get("matched_host_secret_names")
        and not report.get("typesafe_env_names")
        and report.get("docker_socket_present") is False
        and report.get("workspace_git_present") is False
        and report.get("repo_git_present") is False
        and report.get("external_network_reachable") is False
        and expected_files.issubset(actual_files)
    )
    safe_report = {
        "passed": passed,
        "checked_host_secret_names": sorted(secret_hashes),
        "matched_host_secret_names": list(report.get("matched_host_secret_names") or []),
        "typesafe_env_names": list(report.get("typesafe_env_names") or []),
        "docker_socket_present": bool(report.get("docker_socket_present")),
        "workspace_git_present": bool(report.get("workspace_git_present")),
        "repo_git_present": bool(report.get("repo_git_present")),
        "external_network_reachable": bool(report.get("external_network_reachable")),
        "visible_workspace_files": sorted(actual_files),
        "inspect_log": logs[0].location,
    }
    atomic_write_json(output_root / "guardrail-probe.json", safe_report)
    if not passed:
        raise WorkflowError("Inspect guardrail probe detected a sandbox isolation violation")
    return safe_report


def _deterministic_output_for_view(view_path: Path) -> dict[str, Any]:
    view, expected, _ = _load_view(view_path, study="routing-semantic-v1")
    del view
    records: list[dict[str, Any]] = []
    defaults: dict[str, Any] = {
        "routing.task_class": "implementation",
        "routing.interaction_required": False,
        "routing.semantic_risk": 0,
    }
    for case_id, decision_ids in expected.items():
        records.append(
            {
                "case_id": case_id,
                "labels": {
                    decision_id: defaults[decision_id]
                    for decision_id in sorted(decision_ids)
                },
            }
        )
    return {"records": records}


def _direct_wrapper_parity(
    *,
    module_path: Path,
    runtime_lock_path: Path,
    view_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    module = validate_abc_adjudication_module(module_path)
    runtime_lock = _load_runtime_lock(runtime_lock_path, module)
    repo = _repo_root(module_path)
    codex_version = str(runtime_lock["codex_cli"]["resolved"])
    safe_version = re.sub(r"[^A-Za-z0-9_.-]+", "-", codex_version)
    image = f"agent-workflow-oracle-adjudicator:qualification-{safe_version}"

    build = subprocess.run(
        [
            "docker",
            "build",
            "--pull",
            "--build-arg",
            f"CODEX_VERSION={codex_version}",
            "-f",
            str(repo / "docker" / "adjudication" / "Dockerfile"),
            "-t",
            image,
            str(repo),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if build.returncode != 0:
        raise WorkflowError(
            "direct-Docker qualification image build failed: "
            + (build.stderr or build.stdout)[-4000:]
        )
    image_id = _run_version_command(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"]
    )

    direct_root = output_root / "direct-wrapper-parity"
    input_dir = direct_root / "input"
    output_dir = direct_root / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    view, expected, view_sha256 = _load_view(
        view_path,
        study="routing-semantic-v1",
    )
    metadata_record = {
        "study_id": view["study_id"],
        "dataset_version": view["dataset_version"],
        "protocol_version": _study_spec("routing-semantic-v1")["oracle_policy"][
            "protocol_version"
        ],
        "input_view_sha256": view_sha256,
        "adjudicator_id": "qualification-direct",
        "expected_records": [
            {
                "case_id": case_id,
                "decision_ids": sorted(decision_ids),
            }
            for case_id, decision_ids in expected.items()
        ],
    }
    deterministic_output = _deterministic_output_for_view(view_path)
    atomic_write_json(input_dir / "pass-metadata.json", metadata_record)
    atomic_write_json(output_dir / "model-output.json", deterministic_output)

    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--network",
            "none",
            "-v",
            f"{input_dir.resolve()}:/input:ro",
            "-v",
            f"{output_dir.resolve()}:/output:rw",
            "--entrypoint",
            "node",
            image,
            "/opt/aw-adjudication/wrap-output.mjs",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if run.returncode != 0:
        raise WorkflowError(
            "direct-Docker wrapper parity run failed: "
            + (run.stderr or run.stdout)[-4000:]
        )

    direct_contract = _read_json(output_dir / "adjudication.json")
    inspect_contract = _wrap_pass(
        view_path,
        deterministic_output,
        adjudicator_id="qualification-direct",
        study="routing-semantic-v1",
    )
    direct_normalized = copy.deepcopy(direct_contract)
    inspect_normalized = copy.deepcopy(inspect_contract)
    direct_normalized["completed_at"] = "<normalized>"
    inspect_normalized["completed_at"] = "<normalized>"
    passed = direct_normalized == inspect_normalized
    report = {
        "passed": passed,
        "image": image,
        "image_id": image_id,
        "codex_cli_version": codex_version,
        "view_sha256": view_sha256,
        "direct_contract_sha256": sha256_file(output_dir / "adjudication.json"),
        "normalized_contract_equal": passed,
    }
    atomic_write_json(direct_root / "parity-report.json", report)
    if not passed:
        raise WorkflowError(
            "Inspect adapter output is not contract-equivalent to direct-Docker wrapper"
        )
    return report


def _forced_disagreement_passes(
    *,
    view_path: Path,
    primary_manifest: Mapping[str, Any],
    output_root: Path,
) -> tuple[Path, Path]:
    a_source = Path(primary_manifest["outputs"]["A"]["path"])
    a = _read_json(a_source)
    forced_a = copy.deepcopy(a)
    forced_b = copy.deepcopy(a)
    forced_a["adjudicator_id"] = "qualification-forced-a"
    forced_b["adjudicator_id"] = "qualification-forced-b"
    forced_a["completed_at"] = _utc()
    forced_b["completed_at"] = _utc()
    if not forced_b["records"]:
        raise WorkflowError("synthetic primary result unexpectedly contains no records")
    labels = forced_b["records"][0]["labels"]
    current = bool(labels["routing.interaction_required"])
    labels["routing.interaction_required"] = not current

    forced_root = output_root / "forced-dispute"
    forced_root.mkdir(parents=True, exist_ok=True)
    a_path = forced_root / "adjudication-a.json"
    b_path = forced_root / "adjudication-b.json"
    atomic_write_json(a_path, forced_a)
    atomic_write_json(b_path, forced_b)
    validate_adjudication_pass(view_path, a_path, study="routing-semantic-v1")
    validate_adjudication_pass(view_path, b_path, study="routing-semantic-v1")
    return a_path, b_path


def run_inspect_live_qualification(
    module_path: Path,
    runtime_lock_path: Path,
    destination: Path,
    *,
    model: str,
    model_args: Mapping[str, Any] | None = None,
    force: bool = False,
    log_model_api: bool = False,
) -> dict[str, Any]:
    module_path = Path(module_path)
    runtime_lock_path = Path(runtime_lock_path)
    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"Inspect qualification manifest already exists: {destination}")
    module = validate_abc_adjudication_module(module_path)
    runtime_lock = _load_runtime_lock(runtime_lock_path, module)
    root = destination.parent / "inspect-qualification"
    if root.exists() and any(root.iterdir()) and not force:
        raise WorkflowError(f"Inspect qualification evidence directory already exists: {root}")
    root.mkdir(parents=True, exist_ok=True)

    synthetic_view = root / "synthetic-oracle-view.json"
    synthetic_protocol = root / "synthetic-protocol.md"
    _synthetic_qualification_view(synthetic_view)
    _synthetic_protocol(synthetic_protocol)

    guardrail = _run_guardrail_probe(
        output_root=root,
        model=model,
        model_args=model_args,
    )

    primary = run_inspect_primary(
        InspectRunConfig(
            module_path=module_path,
            view_path=synthetic_view,
            protocol_path=synthetic_protocol,
            runtime_lock_path=runtime_lock_path,
            output_root=root / "inspect-primary",
            model=model,
            model_args=model_args,
            log_model_api=log_model_api,
            allow_unqualified=True,
        )
    )
    a_validation = validate_adjudication_pass(
        synthetic_view,
        Path(primary["outputs"]["A"]["path"]),
        study="routing-semantic-v1",
    )
    b_validation = validate_adjudication_pass(
        synthetic_view,
        Path(primary["outputs"]["B"]["path"]),
        study="routing-semantic-v1",
    )

    forced_a, forced_b = _forced_disagreement_passes(
        view_path=synthetic_view,
        primary_manifest=primary,
        output_root=root,
    )
    dispute_path = root / "synthetic-disputes-for-c.json"
    dispute = export_oracle_dispute_view(
        synthetic_view,
        forced_a,
        forced_b,
        dispute_path,
        study="routing-semantic-v1",
    )
    if not dispute["requires_c"]:
        raise WorkflowError("synthetic qualification failed to create a required C dispute")

    c_result = run_inspect_tiebreaker(
        InspectRunConfig(
            module_path=module_path,
            view_path=dispute_path,
            protocol_path=synthetic_protocol,
            runtime_lock_path=runtime_lock_path,
            output_root=root / "inspect-c",
            model=model,
            model_args=model_args,
            log_model_api=log_model_api,
            allow_unqualified=True,
        )
    )
    c_validation = validate_adjudication_pass(
        dispute_path,
        Path(c_result["path"]),
        study="routing-semantic-v1",
    )

    synthetic_oracle = root / "synthetic-oracle.json"
    frozen = freeze_oracle_bundle(
        synthetic_view,
        forced_a,
        forced_b,
        synthetic_oracle,
        oracle_version="inspect-qualification-v1",
        c_view_path=dispute_path,
        pass_c_path=Path(c_result["path"]),
        study="routing-semantic-v1",
    )

    wrapper_parity = _direct_wrapper_parity(
        module_path=module_path,
        runtime_lock_path=runtime_lock_path,
        view_path=synthetic_view,
        output_root=root,
    )

    repo = _repo_root(module_path)
    direct_module_path = (
        repo / "modules" / "abc-adjudication" / "routing-semantic-v1.module.json"
    )
    direct_module = _read_json(direct_module_path)
    inspect_module = _read_json(module_path)
    direct_required = {item["id"]: item for item in direct_module["required_files"]}
    inspect_required = {item["id"]: item for item in inspect_module["required_files"]}
    identity_ids = {"oracle-view", "routing-corpus"}
    identity_parity = all(
        direct_required[item]["sha256"] == inspect_required[item]["sha256"]
        for item in identity_ids
    )
    common_prompt = (
        direct_module["prompt"]["template"] == inspect_module["prompt"]["template"]
    )
    if not identity_parity or not common_prompt:
        raise WorkflowError("direct-Docker and Inspect modules do not preserve study input/prompt parity")

    gates = {
        "IA-1": {
            "status": "pass",
            "evidence": {
                "inspect_ai_version": runtime_lock["inspect_ai_version"],
                "inspect_swe_version": runtime_lock["inspect_swe_version"],
                "codex_cli": dict(runtime_lock["codex_cli"]),
                "docker": dict(runtime_lock["docker"]),
            },
        },
        "IA-2": {
            "status": "pass",
            "evidence": {
                "synthetic_primary_completed": True,
                "model": model,
                "host_provider_bridge_required_by_sandbox_network_none": True,
            },
        },
        "IA-3": {
            "status": "pass",
            "evidence": guardrail,
        },
        "IA-4": {
            "status": "pass",
            "evidence": {
                "common_prompt_template": inspect_module["prompt"]["template"],
                "common_prompt": common_prompt,
                "canonical_identity_hash_parity": identity_parity,
                "synthetic_view_sha256": sha256_file(synthetic_view),
                "synthetic_protocol_sha256": sha256_file(synthetic_protocol),
            },
        },
        "IA-5": {
            "status": "pass",
            "evidence": wrapper_parity,
        },
        "IA-6": {
            "status": "pass",
            "evidence": {
                "a_pass_sha256": a_validation["pass_sha256"],
                "b_pass_sha256": b_validation["pass_sha256"],
                "reveal_policy": primary["reveal_policy"],
            },
        },
        "IA-7": {
            "status": "pass",
            "evidence": {
                "dispute_view_sha256": dispute["sha256"],
                "c_pass_sha256": c_validation["pass_sha256"],
                "disputed_cases": dispute["disputed_cases"],
                "disputed_seams": dispute["disputed_seams"],
            },
        },
        "IA-8": {
            "status": "pass",
            "evidence": {
                "direct_wrapper_contract_parity": True,
                "synthetic_oracle_sha256": frozen["sha256"],
                "direct_reference_module": str(direct_module_path),
            },
        },
    }
    record = {
        "schema": INSPECT_QUALIFICATION_SCHEMA,
        "created_at": _utc(),
        "module_id": module["module_id"],
        "module_sha256": module["module_sha256"],
        "runtime_lock_sha256": sha256_file(runtime_lock_path),
        "qualified": all(item["status"] == "pass" for item in gates.values()),
        "gates": gates,
    }
    validate_instance(
        record,
        INSPECT_QUALIFICATION_SCHEMA,
        artifact="Inspect adjudication qualification",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        **record,
    }


def inspect_static_qualification(
    module_path: Path,
    destination: Path,
    *,
    runtime_lock_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    module = validate_abc_adjudication_module(module_path)
    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"Inspect qualification manifest already exists: {destination}")
    _require_inspect_dependencies()
    docker = _docker_identity()
    runtime_lock = (
        _load_runtime_lock(runtime_lock_path, module)
        if runtime_lock_path is not None
        else None
    )
    gates = {
        "IA-1": {
            "status": "pass",
            "evidence": {
                "inspect_ai_version": INSPECT_AI_VERSION,
                "inspect_swe_version": INSPECT_SWE_VERSION,
                "docker": docker,
                "codex_cli": (
                    dict(runtime_lock["codex_cli"]) if runtime_lock is not None else None
                ),
            },
        },
        "IA-2": {"status": "pending", "reason": "requires authenticated provider bridge smoke"},
        "IA-3": {
            "status": "partial",
            "reason": "declarative guardrails validated; live sandbox probe still required",
        },
        "IA-4": {"status": "pending", "reason": "requires backend materialization parity fixture"},
        "IA-5": {"status": "pending", "reason": "requires deterministic adapter parity fixture"},
        "IA-6": {"status": "pending", "reason": "requires synthetic A/B execution"},
        "IA-7": {"status": "pending", "reason": "requires synthetic C-dispute execution"},
        "IA-8": {"status": "pending", "reason": "requires complete synthetic rollback comparison"},
    }
    record = {
        "schema": INSPECT_QUALIFICATION_SCHEMA,
        "created_at": _utc(),
        "module_id": module["module_id"],
        "module_sha256": module["module_sha256"],
        "runtime_lock_sha256": (
            sha256_file(runtime_lock_path) if runtime_lock_path is not None else None
        ),
        "qualified": all(item["status"] == "pass" for item in gates.values()),
        "gates": gates,
    }
    validate_instance(
        record,
        INSPECT_QUALIFICATION_SCHEMA,
        artifact="Inspect adjudication qualification",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), "sha256": sha256_file(destination), **record}
