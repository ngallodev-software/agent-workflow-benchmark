"""Pinned external benchmark target checkout preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema_contracts import read_contract
from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run

BENCHMARK_TARGET_SCHEMA = "agent-workflow/benchmark-target/v1"


def _git(repo: Path, *args: str) -> str:
    return str(
        run(
            ["git", "-C", str(repo), *args],
            environment=EnvironmentPolicy(unsafe_inherit=True, git_config_policy="operator"),
        ).stdout
    ).strip()


def prepare_target(manifest_path: Path, destination: Path) -> dict[str, Any]:
    """Clone/fetch one manifest-pinned target and verify its Git identities."""
    manifest_path = manifest_path.expanduser().resolve()
    target = read_contract(manifest_path, BENCHMARK_TARGET_SCHEMA)
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not (destination / ".git").exists():
            raise WorkflowError(f"benchmark target destination is not a Git checkout: {destination}")
        if _git(destination, "status", "--porcelain"):
            raise WorkflowError(f"benchmark target destination is dirty: {destination}")
        if _git(destination, "remote", "get-url", "origin") != target["remote"]:
            raise WorkflowError("benchmark target origin does not match manifest remote")
    else:
        run(["git", "clone", "--no-checkout", str(target["remote"]), str(destination)])
    _git(destination, "fetch", "--no-tags", "origin")
    commit = _git(destination, "rev-parse", "--verify", f"{target['commit']}^{{commit}}")
    if commit != target["commit"]:
        raise WorkflowError(f"benchmark target commit mismatch: expected {target['commit']}, observed {commit}")
    tree = _git(destination, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if tree != target["tree"]:
        raise WorkflowError(f"benchmark target tree mismatch: expected {target['tree']}, observed {tree}")
    _git(destination, "checkout", "--detach", "--force", commit)
    if _git(destination, "status", "--porcelain"):
        raise WorkflowError("benchmark target checkout is not clean after detached checkout")
    return {
        "target_id": target["target_id"],
        "manifest": str(manifest_path),
        "remote": target["remote"],
        "repository": str(destination),
        "commit": commit,
        "tree": tree,
    }
