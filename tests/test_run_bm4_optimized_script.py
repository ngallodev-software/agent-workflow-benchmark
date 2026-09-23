from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-bm4-optimized.sh"
RECOVERY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "recover-benchmark-visual.sh"


def test_bm4_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bm4_script_runs_gpt6_optimized_scored_audited_study() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "benchmark bm4-export" in text
    assert "structured-direct/v1 vs agent-workflow-optimized/v1" in text
    assert "gpt-6-luna" in text
    assert "high reasoning effort" in text
    assert "BM4_REPETITIONS" in text
    assert "agent-workflow-optimized/v1" in text
    assert "benchmark readiness" in text
    assert "benchmark plan" in text
    assert "benchmark run" in text
    assert "benchmark live-start" in text
    assert "benchmark visual-capture" in text
    assert "benchmark score" in text
    assert "benchmark live-stop" in text
    assert "benchmark consolidate" in text
    assert "benchmark report" in text
    assert text.index("benchmark visual-capture") < text.index("benchmark score")
    assert text.index("benchmark score") < text.index("benchmark consolidate")
    assert text.index("benchmark consolidate") < text.index("benchmark report")
    assert "model_turn_count" in text
    assert "tool_call_count" in text
    assert "command_execution_count" in text
    assert "injected_context_bytes" in text
    assert "injected_context_estimated_tokens" in text
    assert "cached_input_tokens" in text
    assert "reasoning_output_tokens" in text
    assert "AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG" in text
    assert "typesafe-api-audit.jsonl" in text


def test_bm4_script_checks_exported_model_effort_and_treatment() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'executor.get("model") != "gpt-6-luna"' in text
    assert 'executor.get("effort") != "high"' in text
    assert 'candidate.get("treatment_id") != "agent-workflow-optimized/v1"' in text


def test_visual_recovery_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(RECOVERY_SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_visual_recovery_script_preserves_execution_and_surfaces_failures() -> None:
    text = RECOVERY_SCRIPT.read_text(encoding="utf-8")
    assert 'benchmark run "    assert "benchmark runtime-attest" in text
    assert "benchmark live-start" in text
    assert "benchmark visual-capture" in text
    assert "benchmark live-stop" in text
    assert "visual-capture-history" in text
    assert "visual-history" in text
    assert "failure_details" in text
    assert "assessment" in text


def test_bm4_script_fails_fast_before_scoring_on_visual_failure() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    visual = text.index('benchmark visual-capture "$RUN_PLAN"')
    check = text.index("BM4 visual capture failed")
    score = text.index('benchmark score "$RUN_PLAN"')
    assert visual < check < score
    assert "recover-benchmark-visual.sh" in text
 not in text
    assert "benchmark runtime-attest" in text
    assert "benchmark live-start" in text
    assert "benchmark visual-capture" in text
    assert "benchmark live-stop" in text
    assert "visual-capture-history" in text
    assert "visual-history" in text
    assert "failure_details" in text
    assert "assessment" in text


def test_bm4_script_fails_fast_before_scoring_on_visual_failure() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    visual = text.index('benchmark visual-capture "$RUN_PLAN"')
    check = text.index("BM4 visual capture failed")
    score = text.index('benchmark score "$RUN_PLAN"')
    assert visual < check < score
    assert "recover-benchmark-visual.sh" in text
