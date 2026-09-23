from __future__ import annotations

import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.visual import (
    _archive_failed_summary,
    _archive_failed_visual,
    _assessment_failure_details,
)


def test_assessment_failure_details_prefers_failed_checks() -> None:
    details = _assessment_failure_details(
        {
            "capture_state": "harness_failure",
            "checks": [
                {"id": "capture-harness", "passed": False, "detail": "TimeoutError: page did not load"},
            ],
        },
        stderr="",
        stdout="",
    )
    assert details == ["TimeoutError: page did not load"]


def test_assessment_failure_details_falls_back_to_process_output() -> None:
    details = _assessment_failure_details(
        {"capture_state": "harness_failure", "checks": []},
        stderr="browser launch failed",
        stdout="",
    )
    assert details == ["stderr: browser launch failed"]


def test_archive_failed_visual_preserves_directory(tmp_path: Path) -> None:
    visual = tmp_path / "stage" / "visual"
    visual.mkdir(parents=True)
    (visual / "assessment.json").write_text(
        json.dumps({"capture_state": "harness_failure"}) + "\n",
        encoding="utf-8",
    )
    archived = _archive_failed_visual(visual)
    assert archived == tmp_path / "stage" / "visual-history" / "failed-01"
    assert archived is not None and (archived / "assessment.json").is_file()
    assert not visual.exists()


def test_archive_failed_summary_preserves_prior_result(tmp_path: Path) -> None:
    summary = tmp_path / "visual-capture-summary.json"
    summary.write_text(json.dumps({"harness_failures": 2}) + "\n", encoding="utf-8")
    archived = _archive_failed_summary(summary)
    assert archived == tmp_path / "visual-capture-history" / "failed-01.json"
    assert archived is not None and archived.read_text(encoding="utf-8") == summary.read_text(encoding="utf-8")
