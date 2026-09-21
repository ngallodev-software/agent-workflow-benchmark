from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-install.sh"


def test_build_install_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_build_install_script_documents_shared_venv_and_verify_mode() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "same shared virtualenv" in result.stdout
    assert "--venv PATH" in result.stdout
    assert "--verify-only" in result.stdout
    assert "stale benchmark" in result.stdout
