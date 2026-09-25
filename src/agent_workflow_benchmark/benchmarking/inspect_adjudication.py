from __future__ import annotations

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

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .adjudication_module import validate_abc_adjudication_module
from .oracle_adjudication import (
    ADJUDICATION_PASS_SCHEMA,
    _decision_specs,
    _load_view,
    _study_spec,
    _validate_label,
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
    model_args: Mapping[str, Any] | None = None
    log_model_api: bool = False


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
        role_dir = config.output_root / role.lower()
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
    role_dir = config.output_root / "c"
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), "sha256": sha256_file(destination), **record}
