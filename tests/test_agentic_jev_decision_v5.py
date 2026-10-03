from __future__ import annotations

from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v4 import (
    SOURCE_COMMIT as V4_SOURCE_COMMIT,
    decision_skill_path as v4_skill_path,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v5 import (
    SOURCE_COMMIT,
    SOURCE_HELPER_GIT_BLOB,
    SOURCE_OPENAI_GIT_BLOB,
    SOURCE_SKILL_GIT_BLOB,
    decision_skill_interface_path,
    decision_skill_path,
    source_manifest,
)


def test_v5_tracks_new_source_without_mutating_v4() -> None:
    assert SOURCE_COMMIT == "4688bdf38e95e65725f6c7def5307dd8db39a702"
    assert SOURCE_SKILL_GIT_BLOB == "8cda894da2c83421a21d13c296d0f71e4742916d"
    assert SOURCE_OPENAI_GIT_BLOB == "481204922312cee343323181a06788db29ecbc6e"
    assert SOURCE_HELPER_GIT_BLOB == "f5c24b6349c3240c10efa901a38d078c91e44073"
    assert V4_SOURCE_COMMIT == "d0ac1ef45d1b79b18b2905872c62cb9e68d961c7"
    assert decision_skill_path() != v4_skill_path()
    assert decision_skill_path().is_file()
    assert decision_skill_interface_path().is_file()


def test_v5_skill_requires_complete_structured_requests_and_changed_revisions() -> None:
    text = decision_skill_path().read_text(encoding="utf-8")

    assert "Build the request deliberately" in text
    assert "shape and identity" in text
    assert "task adapter owns completeness" in text
    assert "insufficient_evidence" in text
    assert "evidence-sufficiency Noul" in text
    assert "Batch parallel judgments; chain only after state changes" in text
    assert "cannot see one another's answers" in text
    assert "Do **not** make a second semantic call merely because confidence is low" in text
    assert "request hash must" in text
    assert "host-side" in text and "jev_system_one" in text
    assert "Do **not** install or import `typesafe-sdk`" in text


def test_v5_manifest_marks_future_only_boundary() -> None:
    manifest = source_manifest()
    assert manifest["live_treatment_defined"] is False
    assert manifest["supersedes_for_future_studies"] == "agentic-jev-decision-v4"
    assert manifest["completed_v1_runtime_unchanged"] is True
    assert len(manifest["benchmark_skill_sha256"]) == 64
    assert len(manifest["benchmark_interface_sha256"]) == 64
