from __future__ import annotations

import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "scripts" / "finalize-bm4.sh"
PUBLISHER = ROOT / "scripts" / "prepare-bm4-publication.py"


def test_bm4_finalizer_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(FINALIZER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bm4_publication_builder_compiles(tmp_path: Path) -> None:
    py_compile.compile(
        str(PUBLISHER),
        cfile=str(tmp_path / "prepare-bm4-publication.pyc"),
        doraise=True,
    )


def test_finalizer_does_not_rerun_model_execution() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    assert 'benchmark run "$' not in text
    assert "benchmark score" in text
    assert "benchmark consolidate" in text
    assert "benchmark report" in text
    assert "collect-value-smoke-evidence.py" in text
    assert "prepare-bm4-publication.py" in text


def test_finalizer_copies_public_evidence_to_results_repo() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    assert "agent-workflow-benchmark-results" in text
    assert 'PUBLIC_DEST="$RESULTS_REPO/bm4"' in text
    assert "--commit-results" in text
    assert "--push-results" in text
    assert "git -C \"$RESULTS_REPO\" push" in text


def test_publication_excludes_raw_typesafe_and_private_receipts() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    assert "raw_audit_published" in text
    assert '"raw_typesafe_audit_published": False' in text
    assert "private-receipt-hashes.json" in text
    assert "published_raw" in text
    assert "copy_file(run_dir / name" not in text


def test_publication_includes_portfolio_evidence() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    for required in (
        "final-project",
        "score.json",
        "product-score.json",
        "timing.json",
        "usage.json",
        "desktop.png",
        "tablet.png",
        "mobile.png",
        "analysis",
        "comparison.md",
        "visual-harness-correction.json",
        "typesafe-qualification-summary.json",
    ):
        assert required in text


def test_publication_preserves_existing_bm4_metadata() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    assert "generated_entries" in text
    assert '"optimization-ledger.md"' not in text
    assert "shutil.rmtree(destination)" not in text


def test_bm4_publication_includes_product_scoring_contract_and_metric() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    assert "product-scoring-contract.json" in text
    assert '"product_score"' in text
    assert "Supplementary product score" in text
