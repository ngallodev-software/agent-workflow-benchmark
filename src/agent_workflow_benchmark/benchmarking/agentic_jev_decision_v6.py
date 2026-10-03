"""Benchmark Jev decision-support skill v6 for SWE-manager v2 studies."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from agent_workflow.util import sha256_file

SOURCE_REPOSITORY = "ngallodev-software/jev-decision-support"
SOURCE_COMMIT = "4688bdf38e95e65725f6c7def5307dd8db39a702"
SOURCE_PATH = "skills/jev-decision-support/SKILL.md"
BENCHMARK_PARENT_GENERATION = "agentic-jev-decision-v5"


def decision_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v6/jev-decision-support/SKILL.md"
    )
    return Path(str(resource))


def decision_skill_sha256() -> str:
    return sha256_file(decision_skill_path())


def decision_skill_interface_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v6/jev-decision-support/agents/openai.yaml"
    )
    return Path(str(resource))


def decision_skill_interface_sha256() -> str:
    return sha256_file(decision_skill_interface_path())


def source_manifest() -> dict[str, Any]:
    return {
        "repository": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "path": SOURCE_PATH,
        "benchmark_parent_generation": BENCHMARK_PARENT_GENERATION,
        "benchmark_skill_sha256": decision_skill_sha256(),
        "benchmark_interface_sha256": decision_skill_interface_sha256(),
        "host_tool": "jev_manager_decision",
        "authoritative_task_context_host_injected": True,
        "max_changed_revisions_documented": 1,
        "completed_v1_runtime_unchanged": True,
    }
