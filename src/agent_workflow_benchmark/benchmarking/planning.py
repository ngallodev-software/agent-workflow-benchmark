from __future__ import annotations

import importlib.metadata
import json
import platform
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent_workflow.config import Settings
from agent_workflow.errors import WorkflowError
from agent_workflow.git import assert_clean, snapshot
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import atomic_write_json, sha256_file, utc_now, validate_id
from agent_workflow.worktrees import create as create_worktree
from .auth import require_authentication
from .common import canonical_json_sha256, child, copy_tree, read_object, text_sha256, tree_sha256
from .contracts import (
    BENCHMARK_RUN_SCHEMA,
    contract_sha256,
    normalized_arm_profiles,
    run_schema_for_spec,
    load_scoring_contract,
    validate_executor_config,
    validate_spec,
    validate_value,
)
from .events import append_event
from .policy import apply_operating_policy, implicit_operating_policy, load_operating_policy
from .runtime import validate_runtime_lock
from .treatments import require_treatment_runtime_compatibility

NEUTRAL_ENVELOPE = """# Benchmark-neutral execution envelope

Work only inside the current Git worktree. Do not inspect parent or sibling directories,
other worktrees, hidden evaluator files, credentials, or unrelated host state. Do not
change the canonical task requirements. Stop when the requested phase is complete.
All benchmark-owned evidence paths are host managed and are not task deliverables.
"""


def _run_id(benchmark_id: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{benchmark_id}-{stamp}-{secrets.token_hex(3)}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"cannot read benchmark input {path}: {exc}") from exc


def _git_version() -> str | None:
    result = run(["git", "--version"], check=False, probe_version=False)
    value = str(result.stdout).strip()
    return value or None


TOOLCHAIN_DISTRIBUTIONS = (
    "agent-workflow",
    "agent-workflow-benchmark",
    "agent-workflow-comparative-eval",
    "specgen-agent-workflow-contracts",
    "typesafe-sdk",
)


def _git_source_identity(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    revision = run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        check=False,
        probe_version=False,
    )
    if revision.returncode != 0:
        return {"source_revision": None, "source_dirty": None}
    status = run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=no"],
        check=False,
        probe_version=False,
        environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
    )
    observed = str(revision.stdout).strip()
    return {
        "source_revision": observed if observed else None,
        "source_dirty": bool(str(status.stdout).strip()) if status.returncode == 0 else None,
    }


def _distribution_identity(
    distribution_name: str,
    *,
    fallback_root: Path | None = None,
) -> dict[str, Any] | None:
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return None
    direct_url_text = distribution.read_text("direct_url.json")
    editable = False
    root: Path | None = None
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = {}
        editable = bool(
            isinstance(direct_url.get("dir_info"), dict)
            and direct_url["dir_info"].get("editable")
        )
        raw_url = direct_url.get("url")
        if isinstance(raw_url, str):
            parsed = urlparse(raw_url)
            if parsed.scheme == "file":
                root = Path(unquote(parsed.path))
    if root is None and fallback_root is not None:
        root = fallback_root
    source = (
        _git_source_identity(root)
        if root is not None
        else {"source_revision": None, "source_dirty": None}
    )
    return {
        "version": distribution.version,
        "editable": editable,
        **source,
    }


def _stack_source_provenance() -> dict[str, dict[str, Any]]:
    path = Path(sys.prefix) / "share" / "agent-workflow" / "source-provenance.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema") != "agent-workflow/source-provenance/v1":
        return {}
    components = value.get("components")
    if not isinstance(components, dict):
        return {}
    return {
        str(name): dict(item)
        for name, item in components.items()
        if isinstance(name, str) and isinstance(item, dict)
    }


def _toolchain_identity() -> dict[str, Any]:
    identities: dict[str, Any] = {}
    benchmark_root = Path(__file__).resolve().parents[3]
    installed_sources = _stack_source_provenance()
    for name in TOOLCHAIN_DISTRIBUTIONS:
        identity = _distribution_identity(
            name,
            fallback_root=benchmark_root if name == "agent-workflow-benchmark" else None,
        )
        installed = installed_sources.get(name)
        if identity is None:
            if installed is None:
                continue
            identity = {
                "version": installed.get("version"),
                "editable": False,
                "source_revision": None,
                "source_dirty": None,
            }
        if (
            installed is not None
            and installed.get("version") == identity.get("version")
            and isinstance(installed.get("revision"), str)
            and installed.get("revision")
        ):
            identity["source_revision"] = installed["revision"]
            identity["source_dirty"] = (
                installed.get("dirty")
                if isinstance(installed.get("dirty"), bool)
                else None
            )
            identity["source_provenance"] = "stack-install-manifest"
        elif identity.get("source_revision"):
            identity["source_provenance"] = "package-source"
        else:
            identity["source_provenance"] = "unavailable"
        identities[name] = identity
    return identities


def _environment_identity(executor: dict[str, Any], codebase_memory_mode: str) -> dict[str, Any]:
    value = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "git": _git_version(),
        "locale": "C",
        "timezone": "UTC",
        "codebase_memory_mode": codebase_memory_mode,
        "toolchain": _toolchain_identity(),
        "executor": {
            "provider": executor["provider"],
            "executor": executor["executor"],
            "executor_version": executor["executor_version"],
            "model": executor["model"],
            "effort": executor.get("effort"),
            "sandbox": executor["sandbox"],
            "authentication_mode": executor["authentication"]["mode"],
            "billing_mode": executor["billing"]["mode"],
        },
    }
    value["sha256"] = canonical_json_sha256(value)
    return value


def _effective_prompt(*, canonical_task: str, phase_prompt: str, wrapper: str, arm: str, treatment_id: str, phase_id: str, case_id: str, codebase_memory_mode: str) -> str:
    return "\n\n".join(
        [
            NEUTRAL_ENVELOPE.strip(),
            f"# Benchmark identity\n\nArm slot: `{arm}`\nTreatment: `{treatment_id}`\nCase: `{case_id}`\nPhase: `{phase_id}`",
            f"# Codebase-memory tool mode\n\nUse only `{codebase_memory_mode}` for codebase-memory assistance in this cohort. Do not use another codebase-memory integration.",
            "# Canonical task\n\n" + canonical_task.strip(),
            "# Current phase\n\n" + phase_prompt.strip(),
            "# Arm execution profile\n\n" + wrapper.strip(),
        ]
    ) + "\n"


def materialize_fixture(spec_path: Path, destination: Path, *, force: bool = False) -> dict[str, Any]:
    spec_path = spec_path.expanduser().resolve()
    spec = validate_spec(spec_path)
    source = child(spec_path.parent, spec["fixture"]["template_path"], "fixture template")
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise WorkflowError(f"fixture destination already exists: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    copy_tree(source, destination)
    run(["git", "init", "-q", str(destination)])
    run(["git", "-C", str(destination), "config", "user.name", "Benchmark Fixture"])
    run(["git", "-C", str(destination), "config", "user.email", "benchmark@example.invalid"])
    run(["git", "-C", str(destination), "add", "--all"])
    run(["git", "-C", str(destination), "commit", "-q", "-m", "priority-picker-v1 starter fixture"])
    snap = snapshot(destination)
    return {
        "benchmark_id": spec["benchmark_id"],
        "destination": str(destination),
        "revision": snap.head,
        "fixture_sha256": tree_sha256(destination, exclude=(".git",)),
        "clean": not snap.dirty,
    }


def _copy_suite(spec_path: Path, destination: Path) -> None:
    copy_tree(spec_path.parent, destination, ignore={"__pycache__", ".pytest_cache", "runs"})


def _remove_created(source_root: Path, created: list[dict[str, Any]]) -> None:
    for info in reversed(created):
        destination = Path(str(info.get("destination", "")))
        if destination.exists():
            run(
                ["git", "-C", str(source_root), "worktree", "remove", "--force", str(destination)],
                check=False,
                environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
            )
        branch = str(info.get("branch", ""))
        if branch:
            run(
                ["git", "-C", str(source_root), "branch", "-D", branch],
                check=False,
                environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
            )


def create_run_plan(
    settings: Settings,
    *,
    spec_path: Path,
    executor_path: Path,
    repo: Path,
    base_ref: str,
    run_id: str | None = None,
    repetitions: int | None = None,
    worktree_root: Path | None = None,
    allow_dirty: bool = False,
    assistance_cohort: str | None = None,
    policy_path: Path | None = None,
    runtime_lock_path: Path | None = None,
    codebase_memory_mode: str = "none",
) -> dict[str, Any]:
    spec_path = spec_path.expanduser().resolve()
    executor_path = executor_path.expanduser().resolve()
    base_spec = validate_spec(spec_path)
    executor = validate_executor_config(executor_path)
    if codebase_memory_mode not in {"none", "mcp", "cli"}:
        raise WorkflowError("benchmark codebase-memory mode must be none, mcp, or cli")
    policy = (
        load_operating_policy(policy_path)
        if policy_path is not None
        else implicit_operating_policy(base_spec)
    )
    effective_policy = {**policy, "winner_policy": dict(policy["winner_policy"])}
    overrides: dict[str, Any] = {}
    if policy_path is not None and str(policy["claim_level"]) != "development":
        requested_overrides = [
            name
            for name, value in (("repetitions", repetitions), ("assistance_cohort", assistance_cohort))
            if value is not None
        ]
        if requested_overrides:
            raise WorkflowError(
                "internal/publication benchmark policies may not be overridden on the command line; "
                "create and validate a distinct versioned policy profile instead: "
                + ", ".join(requested_overrides)
            )
    if repetitions is not None:
        if repetitions < 1:
            raise WorkflowError("benchmark repetitions must be at least 1")
        effective_policy["repetitions"] = repetitions
        overrides["repetitions"] = repetitions
    if assistance_cohort is not None:
        if assistance_cohort not in {"unassisted", "assisted"}:
            raise WorkflowError("benchmark assistance cohort must be unassisted or assisted")
        effective_policy["assistance_cohort"] = assistance_cohort
        overrides["assistance_cohort"] = assistance_cohort
    spec = apply_operating_policy(
        base_spec,
        effective_policy,
        authentication_mode=str(executor["authentication"]["mode"]),
    )
    assistance_cohort = str(effective_policy["assistance_cohort"])
    selected_runtime_lock = (
        runtime_lock_path.expanduser().resolve()
        if runtime_lock_path is not None
        else child(spec_path.parent, str(base_spec["visual"]["runtime_lock_path"]), "visual runtime lock")
    )
    if not selected_runtime_lock.is_file():
        raise WorkflowError(f"visual runtime lock not found: {selected_runtime_lock}")
    validate_runtime_lock(
        read_object(selected_runtime_lock),
        claim_level=str(spec["claim_level"]),
    )
    treatment_runtime_checks = require_treatment_runtime_compatibility(settings, spec, executor)
    authentication_evidence = require_authentication(executor)
    repo = repo.expanduser().resolve()
    source = snapshot(repo) if allow_dirty else assert_clean(repo)
    base_revision = str(run(["git", "-C", str(source.root), "rev-parse", "--verify", f"{base_ref}^{{commit}}" ]).stdout).strip()
    requested_repetitions = int(effective_policy["repetitions"])
    run_id = validate_id(run_id or _run_id(str(spec["benchmark_id"])), "benchmark run ID")
    root = (worktree_root or settings.worktree_root).expanduser().resolve() / "benchmarks" / run_id
    coordinator = root / "coordinator"
    if root.exists():
        raise WorkflowError(f"benchmark worktree root already exists: {root}")

    fixture_template = child(spec_path.parent, spec["fixture"]["template_path"], "fixture template")
    fixture_sha256 = tree_sha256(fixture_template)
    created_worktrees: list[dict[str, Any]] = []
    try:
        coordinator_info = create_worktree(
            settings, repo=source.root, ticket_id=f"benchmark-{run_id}-coordinator",
            base_ref=base_revision, destination=coordinator,
            branch=f"benchmark/{run_id}/coordinator", allow_dirty=allow_dirty,
        )
        created_worktrees.append(coordinator_info)
        checkout_fixture_sha256 = tree_sha256(coordinator, exclude=(".git",))
        if checkout_fixture_sha256 != fixture_sha256:
            raise WorkflowError(
                "benchmark source revision does not match the frozen fixture template: "
                f"expected {fixture_sha256}, observed {checkout_fixture_sha256}"
            )
        fixture_input = child(coordinator, spec["fixture"]["target_input_path"], "fixture target input")
        if not fixture_input.is_file():
            raise WorkflowError(f"fixture target input not found: {fixture_input}")
        run_dir = coordinator / "benchmarks" / "runs" / run_id
        # The coordinator and worktree root already carry run_id.  Repeating
        # it inside every stage made otherwise valid runs exceed filesystem
        # path limits after agents had spent their token budget.
        suite_dir = coordinator / ".agent-workflow-benchmark" / "suite"
        _copy_suite(spec_path, suite_dir)
        suite_spec = suite_dir / spec_path.name
        runtime_lock_name = "visual-runtime-lock.effective.json"
        shutil.copy2(selected_runtime_lock, suite_dir / runtime_lock_name)
        spec["visual"]["runtime_lock_path"] = runtime_lock_name
        atomic_write_json(suite_spec, spec)
        validate_spec(suite_spec)
        scoring_contract = load_scoring_contract(suite_spec, spec)
        scoring_identity = None
        if scoring_contract is not None:
            scoring_contract_path = suite_dir / str(spec["scoring_contract_path"])
            evaluator_ref = str(scoring_contract["evaluator_path"])
            evaluator_sha256 = None
            if not evaluator_ref.startswith("external://"):
                evaluator_sha256 = sha256_file(suite_dir / evaluator_ref)
            scoring_identity = {
                "contract_path": str(spec["scoring_contract_path"]),
                "benchmark_version": str(spec["version"]),
                "scorer_version": str(scoring_contract["scorer_version"]),
                "evaluator_version": str(scoring_contract["evaluator_version"]),
                "scoring_contract_sha256": sha256_file(scoring_contract_path),
                "evaluator_ref": evaluator_ref,
                "evaluator_sha256": evaluator_sha256,
            }
        executor_snapshot = run_dir / "executor-config.json"
        policy_snapshot = run_dir / "operating-policy.json"
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(executor_path, executor_snapshot)
        atomic_write_json(policy_snapshot, effective_policy)

        canonical_task = _read_text(child(spec_path.parent, spec["canonical_task"], "canonical task"))
        phase_values: list[dict[str, Any]] = []
        phase_contents: list[dict[str, str]] = []
        for phase in spec["phases"]:
            content = _read_text(child(spec_path.parent, phase["prompt_path"], "phase prompt"))
            phase_values.append({
                "id": phase["id"], "name": phase["name"], "prompt_path": phase["prompt_path"],
                "prompt_sha256": text_sha256(content),
                "timeout_seconds": phase.get("timeout_seconds") or executor["timeout_seconds"],
            })
            phase_contents.append({"id": str(phase["id"]), "content": content})
        task_prompt_sha256 = canonical_json_sha256({"canonical_task": canonical_task, "phases": phase_contents})
        environment = _environment_identity(executor, codebase_memory_mode)
        tool_policy_sha256 = canonical_json_sha256({"tool_policy": executor.get("tool_policy", {}), "codebase_memory_mode": codebase_memory_mode})
        resource_policy_sha256 = canonical_json_sha256({
            "timeout_seconds": executor["timeout_seconds"],
            "max_stdout_bytes": executor["max_stdout_bytes"],
            "max_stderr_bytes": executor["max_stderr_bytes"],
            "pair_concurrency": spec["scheduling"]["pair_concurrency"],
            "infrastructure_retries": spec["scheduling"]["infrastructure_retries"],
            "cache_policy": effective_policy["cache_policy"],
            "retry_policy": effective_policy["retry_policy"],
            "interrupted_pair_policy": effective_policy["interrupted_pair_policy"],
        })
        profiles: dict[str, dict[str, Any]] = {}
        normalized_profiles = normalized_arm_profiles(spec)
        for arm, profile in normalized_profiles.items():
            wrapper = _read_text(child(spec_path.parent, profile["wrapper_path"], f"{arm} wrapper"))
            inventory = {
                "profile_id": profile["profile_id"],
                "treatment_id": profile["treatment_id"],
                "source_role": profile["_source_role"],
                "runner": profile["runner"],
                "wrapper_sha256": text_sha256(wrapper),
                "enabled_features": profile["enabled_features"], "disabled_features": profile["disabled_features"],
            }
            profiles[arm] = {**inventory, "constraint_profile_sha256": canonical_json_sha256(inventory), "wrapper": wrapper}

        retries = int(spec["scheduling"]["infrastructure_retries"])
        pairs: list[dict[str, Any]] = []
        for case in spec["cases"]:
            input_path = child(spec_path.parent, case["input_path"], "case input")
            input_sha256 = sha256_file(input_path)
            if input_sha256 != sha256_file(fixture_input):
                raise WorkflowError(f"case {case['id']} input does not match fixture target {spec['fixture']['target_input_path']}")
            for repetition in range(1, requested_repetitions + 1):
                pair_id = f"{case['id']}-r{repetition:02d}"
                attempts: list[dict[str, Any]] = []
                for attempt_number in range(1, retries + 2):
                    attempt_id = f"{pair_id}-a{attempt_number:02d}"
                    pair_nonce = secrets.token_hex(16)
                    slots = ["control_raw", "workflow_full"]
                    if int(pair_nonce[-1], 16) % 2:
                        slots.reverse()
                    arms: dict[str, Any] = {}
                    for slot, arm in zip(("A", "B"), slots, strict=True):
                        destination = root / str(case["id"]) / f"r{repetition:02d}" / f"attempt-{attempt_number:02d}" / arm
                        branch = f"benchmark/{run_id}/{case['id']}/r{repetition:02d}/a{attempt_number:02d}/{arm}"
                        info = create_worktree(
                            settings, repo=source.root, ticket_id=f"benchmark-{run_id}-{attempt_id}-{arm}",
                            base_ref=base_revision, destination=destination, branch=branch, allow_dirty=allow_dirty,
                        )
                        created_worktrees.append(info)
                        stage = destination / ".agent-workflow-benchmark" / str(case["id"]) / f"r{repetition:02d}" / f"attempt-{attempt_number:02d}" / arm
                        prompts_dir = stage / "prompts"
                        prompts_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(input_path, stage / "case-input.json")
                        effective_prompts: list[dict[str, Any]] = []
                        for phase in spec["phases"]:
                            prompt = _effective_prompt(
                                canonical_task=canonical_task,
                                phase_prompt=_read_text(child(spec_path.parent, phase["prompt_path"], "phase prompt")),
                                wrapper=profiles[arm]["wrapper"], arm=arm,
                                treatment_id=profiles[arm]["treatment_id"],
                                phase_id=str(phase["id"]), case_id=str(case["id"]),
                                codebase_memory_mode=codebase_memory_mode,
                            )
                            prompt_file = prompts_dir / f"{phase['id']}.md"
                            prompt_file.write_text(prompt, encoding="utf-8")
                            effective_prompts.append({
                                "phase_id": phase["id"], "path": str(prompt_file),
                                "effective_prompt_sha256": text_sha256(prompt),
                            })
                        arms[arm] = {
                            "arm": arm, "slot": slot, "profile_id": profiles[arm]["profile_id"],
                            "constraint_profile_sha256": profiles[arm]["constraint_profile_sha256"],
                            "arm_wrapper_sha256": profiles[arm]["wrapper_sha256"],
                            "task_prompt_sha256": task_prompt_sha256, "worktree": str(destination),
                            "branch": info["branch"], "stage_dir": str(stage), "prompts": effective_prompts,
                        }
                    attempts.append({
                        "attempt": attempt_number, "attempt_id": attempt_id,
                        "pair_nonce": pair_nonce, "slot_order": slots, "arms": arms,
                    })
                first = attempts[0]
                pairs.append({
                    "pair_id": pair_id, "case_id": case["id"], "repetition": repetition,
                    "pair_nonce": first["pair_nonce"], "slot_order": first["slot_order"],
                    "base_revision": base_revision, "fixture_sha256": fixture_sha256,
                    "input_bundle_sha256": input_sha256, "task_prompt_sha256": task_prompt_sha256,
                    "environment_sha256": environment["sha256"], "tool_policy_sha256": tool_policy_sha256,
                    "resource_policy_sha256": resource_policy_sha256, "allowed_scope": case["allowed_scope"],
                    "arms": first["arms"], "attempts": attempts,
                })

        run_schema = run_schema_for_spec(spec)
        treatments = {
            arm: {
                "source_role": profiles[arm]["source_role"],
                "treatment_id": profiles[arm]["treatment_id"],
                "runner_kind": profiles[arm]["runner"]["kind"],
                "profile_id": profiles[arm]["profile_id"],
                "agent_class": profiles[arm]["runner"].get("agent_class"),
            }
            for arm in ("control_raw", "workflow_full")
        }
        plan = {
            "schema": run_schema, "run_id": run_id, "benchmark_id": spec["benchmark_id"],
            "benchmark_version": spec["version"], "created_at": utc_now(), "state": "planned",
            "claim_level": spec["claim_level"],
            "source": {"repository": str(source.root), "base_ref": base_ref, "base_revision": base_revision, "source_cleanliness": source.cleanliness_evidence()},
            "coordinator": {"worktree": str(coordinator), "branch": coordinator_info["branch"], "run_dir": str(run_dir), "suite_dir": str(suite_dir), "spec_path": str(suite_spec), "executor_config_path": str(executor_snapshot)},
            "identities": {"spec_sha256": contract_sha256(spec), "suite_sha256": tree_sha256(suite_dir), "fixture_sha256": fixture_sha256, "task_prompt_sha256": task_prompt_sha256, "environment_sha256": environment["sha256"], "tool_policy_sha256": tool_policy_sha256, "resource_policy_sha256": resource_policy_sha256},
            "environment": environment, "executor": executor, "phases": phase_values, "pairs": pairs,
            **({"treatment_runtime_checks": treatment_runtime_checks} if treatment_runtime_checks else {}),
            **({"treatments": treatments} if run_schema != BENCHMARK_RUN_SCHEMA else {}),
            "policies": {
                "max_start_skew_seconds": spec["scheduling"]["max_start_skew_seconds"],
                "pair_concurrency": spec["scheduling"]["pair_concurrency"],
                "infrastructure_retries": retries,
                "human_assistance": assistance_cohort,
                "cache_policy": effective_policy["cache_policy"],
                "retry_policy": effective_policy["retry_policy"],
                "interrupted_pair_policy": effective_policy["interrupted_pair_policy"],
            },
            "operating_policy": {
                "policy": effective_policy,
                "policy_sha256": canonical_json_sha256(effective_policy),
                "source": str(policy_path.expanduser().resolve()) if policy_path is not None else None,
                "overrides": overrides,
                "runtime_lock_source": str(selected_runtime_lock),
                "runtime_lock_sha256": sha256_file(selected_runtime_lock),
            },
            "authentication_evidence": authentication_evidence,
            "codebase_memory_mode": codebase_memory_mode,
        }
        if scoring_identity is not None:
            plan["scoring_identity"] = scoring_identity
        validate_value(plan, run_schema, "benchmark run plan")
        atomic_write_json(run_dir / "run-plan.json", plan)
        atomic_write_json(run_dir / "environment.json", environment)
        atomic_write_json(run_dir / "authentication.json", authentication_evidence)
        atomic_write_json(run_dir / "operating-policy-evidence.json", plan["operating_policy"])
        atomic_write_json(run_dir / "experiment-manifest.json", {
            "schema": "agent-workflow/benchmark-experiment-manifest/v1", "run_id": run_id,
            "benchmark_id": spec["benchmark_id"], "authentication_mode": executor["authentication"]["mode"],
            "codebase_memory_mode": codebase_memory_mode,
            "billing": executor["billing"], "assistance_cohort": assistance_cohort,
            "operating_policy": effective_policy,
            "treatment_runtime_checks": treatment_runtime_checks,
            "arms": {arm: {"source_role": profiles[arm]["source_role"], "treatment_id": profiles[arm]["treatment_id"], "runner_kind": profiles[arm]["runner"]["kind"], "agent_class": profiles[arm]["runner"].get("agent_class"), "profile_id": profiles[arm]["profile_id"], "constraint_profile_sha256": profiles[arm]["constraint_profile_sha256"], "arm_wrapper_sha256": profiles[arm]["wrapper_sha256"], "enabled_features": normalized_profiles[arm]["enabled_features"], "disabled_features": normalized_profiles[arm]["disabled_features"]} for arm in ("control_raw", "workflow_full")},
            "task_prompt_sha256": task_prompt_sha256, "fixture_sha256": fixture_sha256, "composite": spec["composite"],
        })
        atomic_write_json(run_dir / "run.json", {
            "schema": "agent-workflow/benchmark-run-state/v1", "run_id": run_id,
            "benchmark_id": spec["benchmark_id"], "state": "planned", "created_at": plan["created_at"],
            "updated_at": plan["created_at"], "pairs_total": len(pairs), "pairs_terminal": 0,
            "coordinator_worktree": str(coordinator),
        })
        append_event(run_dir, event_type="run_planned", run_id=run_id, payload={"pairs": len(pairs), "repetitions": requested_repetitions, "attempts_per_pair": retries + 1})
        return {
            "run_id": run_id,
            "run_plan": str(run_dir / "run-plan.json"),
            "coordinator_worktree": str(coordinator),
            "run_dir": str(run_dir),
            "pairs": len(pairs),
            "base_revision": base_revision,
            "authentication_mode": executor["authentication"]["mode"],
            "operating_policy": effective_policy["policy_id"],
            "claim_level": spec["claim_level"],
        }
    except Exception:
        _remove_created(source.root, created_worktrees)
        raise
