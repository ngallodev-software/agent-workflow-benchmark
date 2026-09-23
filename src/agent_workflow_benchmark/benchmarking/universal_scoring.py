from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import re
from pathlib import Path
from time import monotonic
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import atomic_write_json, sha256_file

from .common import canonical_json_sha256, format_argv, read_object, safe_relative, tree_sha256
from .schema_contracts import validate_instance

BUNDLE_SCHEMA = "agent-workflow/universal-scoring-bundle/v1"
CACHE_SCHEMA = "agent-workflow/universal-scoring-cache/v1"
DEFAULT_GLOBS = ("**/*.py", "**/*.js", "**/*.html", "**/*.css", "**/*.md", "**/*.json")
DEFAULT_EXCLUDES = (".git/**", ".awb/**", ".agent-workflow-benchmark/**", ".venv/**", "node_modules/**", "**/__pycache__/**", "**/*.pyc")
DEFAULT_ENV = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TERM", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "CODEX_HOME", "TYPESAFE_API_KEY")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def load_bundle_manifest(bundle: Path) -> dict[str, Any]:
    path = bundle.expanduser().resolve() / "bundle.json"
    if not path.is_file():
        raise WorkflowError(f"universal scoring bundle manifest not found: {path}")
    value = read_object(path)
    validate_instance(value, BUNDLE_SCHEMA, artifact=str(path))
    probes = value["probes"]
    for probe_id, probe in probes.items():
        dependencies = [str(item) for item in probe.get("depends_on", [])]
        unknown = sorted(set(dependencies) - set(probes))
        if unknown or probe_id in dependencies:
            raise WorkflowError(f"invalid dependencies for scoring probe {probe_id}: {unknown}")
    for dimension_id, dimension in value["dimensions"].items():
        for check_id, check in dimension["contract_checks"].items():
            seen = set()
            for component in check["components"]:
                component_id = str(component["id"])
                if component_id in seen or str(component["probe"]) not in probes:
                    raise WorkflowError(f"invalid component in {dimension_id}/{check_id}: {component_id}")
                seen.add(component_id)
    return value


def bundle_environment_allowlist(bundle: Path) -> tuple[str, ...]:
    manifest = load_bundle_manifest(bundle)
    names = list(DEFAULT_ENV)
    for value in manifest.get("runtime", {}).get("environment_allowlist", []):
        name = str(value)
        if not ENV_NAME.fullmatch(name):
            raise WorkflowError(f"invalid scoring environment name: {name!r}")
        if name not in names:
            names.append(name)
    return tuple(names)


def _parameter_values(manifest: Mapping[str, Any], evidence_dir: Path) -> dict[str, str]:
    parameters = manifest.get("parameters", {})
    path = evidence_dir / "parameters.json"
    if not path.is_file():
        atomic_write_json(path, parameters)
    values = {"parameters_json": str(path)}
    for key, value in parameters.items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)) and (value is None or isinstance(value, (str, int, float, bool))):
            values[f"param_{key}"] = "" if value is None else str(value)
    return values


def _collect_context(root: Path, include: list[str], exclude: list[str], max_files: int, max_bytes: int) -> list[dict[str, Any]]:
    records = []
    total = 0
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise WorkflowError(f"symlink not permitted in scoring context: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in include):
            continue
        if any(fnmatch.fnmatch(relative, pattern) for pattern in exclude):
            continue
        data = path.read_bytes()
        total += len(data)
        if len(records) >= max_files or total > max_bytes:
            raise WorkflowError("scoring context exceeds configured bounds")
        records.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "content": data.decode("utf-8")})
    return records


def _build_context(manifest: Mapping[str, Any], probe: Mapping[str, Any], bundle: Path, worktree: Path, resolved: Mapping[str, Any]) -> dict[str, Any]:
    config = probe.get("context", {})
    bundle_files = []
    for relative in config.get("bundle_files", []):
        relative = safe_relative(str(relative), "scoring bundle context file")
        path = (bundle / relative).resolve()
        path.relative_to(bundle.resolve())
        data = path.read_bytes()
        bundle_files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "content": data.decode("utf-8")})
    requested = [str(item) for item in config.get("include_probe_outputs", [])]
    missing = [item for item in requested if item not in resolved]
    if missing:
        raise WorkflowError(f"unresolved scoring context probes: {missing}")
    result = {
        "bundle": {"id": manifest["bundle_id"], "version": manifest["version"]},
        "parameters": manifest.get("parameters", {}),
        "source_files": _collect_context(
            worktree,
            [str(item) for item in config.get("worktree_globs", DEFAULT_GLOBS)],
            [str(item) for item in config.get("exclude_globs", DEFAULT_EXCLUDES)],
            int(config.get("max_files", 64)),
            int(config.get("max_total_bytes", 512 * 1024)),
        ),
        "bundle_files": bundle_files,
        "probe_outputs": {item: resolved[item] for item in requested},
    }
    if "static" in config:
        result["static"] = config["static"]
    return result


def _probe_values(manifest: Mapping[str, Any], bundle: Path, worktree: Path, evidence_dir: Path, probe_id: str) -> dict[str, str]:
    probe_dir = evidence_dir / "probes" / probe_id
    probe_dir.mkdir(parents=True, exist_ok=True)
    return {
        "bundle": str(bundle),
        "worktree": str(worktree),
        "evidence_dir": str(evidence_dir),
        "probe_dir": str(probe_dir),
        "probe_result": str(probe_dir / "result.json"),
        **_parameter_values(manifest, evidence_dir),
    }


def _run_command_probe(manifest: Mapping[str, Any], probe_id: str, probe: Mapping[str, Any], bundle: Path, worktree: Path, evidence_dir: Path, environment_allowlist: tuple[str, ...]) -> dict[str, Any]:
    values = _probe_values(manifest, bundle, worktree, evidence_dir, probe_id)
    argv = format_argv([str(item) for item in probe["argv"]], values)
    process = run(
        argv,
        cwd=Path(str(probe.get("cwd", "{worktree}")).format_map(values)).resolve(),
        check=False,
        timeout_seconds=float(probe.get("timeout_seconds", 120)),
        max_stdout_bytes=int(probe.get("max_stdout_bytes", 4 * 1024 * 1024)),
        max_stderr_bytes=int(probe.get("max_stderr_bytes", 4 * 1024 * 1024)),
        environment=EnvironmentPolicy(allowlist=environment_allowlist, values={"PYTHONDONTWRITEBYTECODE": "1"}),
        input_text=(bundle / safe_relative(str(probe["stdin_file"]), "stdin_file")).read_text(encoding="utf-8") if "stdin_file" in probe else (str(probe["stdin"]) if "stdin" in probe else None),
        digest_executable=True,
    )
    probe_dir = Path(values["probe_dir"])
    stdout_path, stderr_path = probe_dir / "stdout.log", probe_dir / "stderr.log"
    stdout_path.write_text(str(process.stdout), encoding="utf-8")
    stderr_path.write_text(str(process.stderr), encoding="utf-8")
    mode = str(probe.get("result_mode", "exit-code"))
    if mode == "exit-code":
        payload = {"passed": process.returncode in [int(item) for item in probe.get("success_exit_codes", [0])], "returncode": process.returncode}
    elif mode == "json-file":
        payload = json.loads(Path(values["probe_result"]).read_text(encoding="utf-8"))
    elif mode == "json-stdout":
        payload = json.loads(str(process.stdout))
    else:
        raise WorkflowError(f"unsupported command result_mode: {mode}")
    return {
        "kind": "command",
        "payload": payload,
        "process": {"argv": argv, "returncode": process.returncode, "duration_seconds": process.duration_seconds, "error_category": process.error_category},
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def _typesafe_answer(answer: object, question_id: str) -> dict[str, Any]:
    score = getattr(answer, "score", None)
    confidence = getattr(answer, "confidence", None)
    probabilities = getattr(answer, "probabilities", None)
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 4:
        raise WorkflowError(f"TypeSafe returned invalid score for {question_id}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise WorkflowError(f"TypeSafe returned invalid confidence for {question_id}")
    if not isinstance(probabilities, Mapping):
        raise WorkflowError(f"TypeSafe omitted probabilities for {question_id}")
    normalized = {str(int(key)): float(value) for key, value in probabilities.items()}
    if set(normalized) != {"0", "1", "2", "3", "4"} or abs(sum(normalized.values()) - 1) > 0.02:
        raise WorkflowError(f"TypeSafe returned invalid probabilities for {question_id}")
    return {"score": round(float(score), 6), "confidence": round(float(confidence), 6), "probabilities": normalized}


def _run_typesafe_probe(manifest: Mapping[str, Any], probe_id: str, probe: Mapping[str, Any], bundle: Path, worktree: Path, resolved: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from typesafe_sdk import Score, TypeSafeClient, TypeSafeError
    except ImportError as exc:
        raise WorkflowError("typesafe-batch probe requires typesafe-sdk") from exc
    questions = {}
    question_spec = {}
    for item in probe["questions"]:
        question_id = str(item["id"])
        criteria = [str(value) for value in item["criteria"]]
        if len(criteria) != 5:
            raise WorkflowError(f"TypeSafe question {question_id} requires exactly five criteria")
        questions[question_id] = Score(instructions=str(item["instructions"]), criteria=criteria)
        question_spec[question_id] = {"instructions": str(item["instructions"]), "criteria": criteria}
    state = _build_context(manifest, probe, bundle, worktree, resolved)
    selected_model = str(probe.get("model") or "").strip() or None
    request_sha256 = canonical_json_sha256({"probe_id": probe_id, "model": selected_model, "state": state, "questions": question_spec})
    started = monotonic()
    try:
        with TypeSafeClient(model=selected_model, timeout=float(probe.get("timeout_seconds", 90))) as client:
            response = client.system_one(state=state, questions=questions)
    except (TypeSafeError, OSError, TimeoutError) as exc:
        raise WorkflowError(f"TypeSafe probe {probe_id} failed ({type(exc).__name__})") from exc
    answers = getattr(response, "scores", None)
    if not isinstance(answers, Mapping) or set(answers) != set(questions):
        raise WorkflowError(f"TypeSafe probe {probe_id} returned incomplete answers")
    usage = getattr(response, "usage", None)
    return {
        "kind": "typesafe-batch",
        "request_sha256": request_sha256,
        "request_id": getattr(response, "request_id", None),
        "model": str(getattr(response, "model", selected_model or "unknown")),
        "answers": {str(key): _typesafe_answer(value, str(key)) for key, value in answers.items()},
        "usage": {"input_tokens": int(getattr(usage, "input_tokens", 0) or 0), "output_tokens": int(getattr(usage, "output_tokens", 0) or 0)},
        "duration_seconds": round(monotonic() - started, 6),
    }
