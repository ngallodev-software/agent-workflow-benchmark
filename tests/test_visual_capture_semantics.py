from __future__ import annotations

import runpy
from pathlib import Path


CAPTURE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "agent_workflow_benchmark"
    / "assets"
    / "benchmarks"
    / "_shared"
    / "priority-picker-v2-fast"
    / "evaluation"
    / "capture_visual.py"
)


def test_solution_check_converts_ui_exception_to_failed_check() -> None:
    namespace = runpy.run_path(str(CAPTURE))
    solution_check = namespace["solution_check"]

    def fail():
        raise TimeoutError("missing control")

    value = solution_check("ui.example", fail)
    assert value["id"] == "ui.example"
    assert value["passed"] is False
    assert "TimeoutError: missing control" in value["detail"]


def test_visual_harness_does_not_hard_code_title_sort_option() -> None:
    text = CAPTURE.read_text(encoding="utf-8")
    assert 'select_option("title")' not in text
    assert "sort_values" in text
    assert "alternate" in text
    assert "solution_check" in text


def test_visual_harness_does_not_require_priority_items_before_evidence_capture() -> None:
    text = CAPTURE.read_text(encoding="utf-8")
    assert "first.wait_for" not in text
    assert 'capture_state": "complete"' in text
