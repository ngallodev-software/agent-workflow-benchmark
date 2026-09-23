from __future__ import annotations

import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-bm5-slimmed.sh"
PUBLISHER = ROOT / "scripts" / "prepare-bm5-publication.py"


def test_bm5_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bm5_script_runs_v3_steering_first_study() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "benchmark bm5-export" in text
    assert "Priority Picker v3" in text
    assert "structured-direct/v1 vs agent-workflow-bm5/v1" in text
    assert "gpt-6-luna" in text
    assert "agent-workflow-bm5/v1" in text
    assert '"agent-workflow": "0.11.9"' in text
    assert '"agent-workflow-benchmark": "0.3.5"' in text
    assert "benchmark visual-capture" in text
    assert "benchmark score" in text
    assert "benchmark consolidate" in text
    assert "benchmark report" in text
    assert "prepare-bm5-publication.py" in text
    assert '$RESULTS_REPO/bm5' in text


def test_bm5_publication_builder_compiles(tmp_path: Path) -> None:
    py_compile.compile(
        str(PUBLISHER),
        cfile=str(tmp_path / "prepare-bm5-publication.pyc"),
        doraise=True,
    )


def test_bm5_publication_keeps_product_and_protocol_evidence() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    assert "product-score.json" in text
    assert "product-scoring-contract.json" in text
    assert "protocol_command_counts" in text
    assert "verification_cache_hits" in text
    assert "finish_invocations" in text
    assert "finish_incomplete_invocations" in text
    assert "finish_outcomes" in text
    assert "OPT-015" in text
    assert '"study_id": "bm5"' in text
    assert "agent-workflow-slimmed" in text
