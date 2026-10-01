"""Source-synchronized benchmark Jev decision-support skill v4.

This module intentionally exposes only immutable skill identity/path helpers.
It does not define a new live experimental treatment. Frozen v2/v3 evidence
continues to resolve through their versioned modules and assets.
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from agent_workflow.util import sha256_file

SOURCE_REPOSITORY = "ngallodev-software/jev-decision-support"
SOURCE_COMMIT = "5b43c3f1cd289361cf7715588cbc3871f2f6947f"
SOURCE_PATH = "skills/jev-decision-support/SKILL.md"
SOURCE_SKILL_GIT_BLOB = "5fcf00bbf5eb51a350ad1fed879e4a19e7753eb2"
SOURCE_OPENAI_GIT_BLOB = "ba931acbdbdd7e1f8327db63f93468e396672d14"


def decision_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v4/jev-decision-support/SKILL.md"
    )
    return Path(str(resource))


def decision_skill_sha256() -> str:
    return sha256_file(decision_skill_path())


def decision_skill_interface_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-decision-v4/jev-decision-support/agents/openai.yaml"
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
        "benchmark_skill_sha256": decision_skill_sha256(),
        "benchmark_interface_sha256": decision_skill_interface_sha256(),
        "live_treatment_defined": False,
    }
