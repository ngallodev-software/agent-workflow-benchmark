"""Source-synchronized benchmark Jev decision-support skill v5.

This module exposes immutable skill identity/path helpers for future studies.
It intentionally does not change the v4 skill/runtime used by the completed
agentic-jev-swe-manager-v1 study.
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from agent_workflow.util import sha256_file

SOURCE_REPOSITORY = "ngallodev-software/jev-decision-support"
SOURCE_COMMIT = "4688bdf38e95e65725f6c7def5307dd8db39a702"
SOURCE_PATH = "skills/jev-decision-support/SKILL.md"
SOURCE_SKILL_GIT_BLOB = "8cda894da2c83421a21d13c296d0f71e4742916d"
SOURCE_OPENAI_GIT_BLOB = "481204922312cee343323181a06788db29ecbc6e"
SOURCE_HELPER_GIT_BLOB = "f5c24b6349c3240c10efa901a38d078c91e44073"


def decision_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v5/jev-decision-support/SKILL.md"
    )
    return Path(str(resource))


def decision_skill_sha256() -> str:
    return sha256_file(decision_skill_path())


def decision_skill_interface_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v5/jev-decision-support/agents/openai.yaml"
    )
    return Path(str(resource))


def decision_skill_interface_sha256() -> str:
    return sha256_file(decision_skill_interface_path())


def source_manifest() -> dict[str, Any]:
    return {
        "repository": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "path": SOURCE_PATH,
        "source_skill_git_blob": SOURCE_SKILL_GIT_BLOB,
        "source_openai_git_blob": SOURCE_OPENAI_GIT_BLOB,
        "source_helper_git_blob": SOURCE_HELPER_GIT_BLOB,
        "benchmark_skill_sha256": decision_skill_sha256(),
        "benchmark_interface_sha256": decision_skill_interface_sha256(),
        "live_treatment_defined": False,
        "supersedes_for_future_studies": "agentic-jev-decision-v4",
        "completed_v1_runtime_unchanged": True,
    }
