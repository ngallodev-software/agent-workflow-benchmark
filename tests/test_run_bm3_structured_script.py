from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-bm3-structured.sh"


def test_bm3_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bm3_script_runs_structured_scored_audited_study() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "structured-value-smoke-export" in text
    assert "structured-direct/v1 vs agent-workflow-full/v1" in text
    assert "benchmark readiness" in text
    assert "benchmark plan" in text
    assert "benchmark run" in text
    assert "benchmark live-start" in text
    assert "benchmark visual-capture" in text
    assert "benchmark score" in text
    assert "benchmark live-stop" in text
    assert "benchmark consolidate" in text
    assert "benchmark report" in text
    assert text.index("benchmark visual-capture") < text.index("benchmark score") < text.index("benchmark consolidate") < text.index("benchmark report")
    assert "BM3_REPETITIONS" in text
    assert "AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG" in text
    assert "typesafe-api-audit.jsonl" in text
    assert "timing_breakdown" in text
    assert "collect-value-smoke-evidence.py" in text
    assert 'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert "0.11.6" in text
    assert "0.3.1" in text


def test_bm3_script_keeps_raw_typesafe_audit_private() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'chmod 600 "$AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG"' in text
    assert "raw TypeSafe" not in text


def test_bm3_script_help_is_self_service() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for value in (
        "--root PATH",
        "--repetitions N",
        "--agent-class NAME",
        "--evidence PATH",
        "structured-direct/v1",
        "agent-workflow-full/v1",
        "machine scoring",
        "TypeSafe",
    ):
        assert value in result.stdout
