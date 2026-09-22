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


def test_build_install_script_uses_venv_local_xdg_runtime() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'export VIRTUAL_ENV="$VENV"' in text
    assert 'export XDG_CONFIG_HOME="$VENV/.xdg/config"' in text
    assert 'export XDG_STATE_HOME="$VENV/.xdg/state"' in text
    assert 'export XDG_DATA_HOME="$VENV/.xdg/data"' in text
    assert "agent-workflow-benchmark" in text
    assert "TYPESAFE_API_KEY" in text
    assert "agent-workflow-comparative-eval" in text
    assert 'mode = "comparative"' in text
    assert 'provider = "typesafe"' in text
    assert "api_call_log" in text
    assert "typesafe-api-calls.jsonl" in text
    assert "typesafe-sdk" in text
    assert "--comparative-eval-source PATH" in subprocess.run(["bash", str(SCRIPT), "--help"], text=True, capture_output=True).stdout
