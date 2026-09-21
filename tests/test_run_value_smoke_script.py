from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-value-smoke.sh"


def test_value_smoke_script_is_valid_codex_only_execution_smoke() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    text = SCRIPT.read_text(encoding="utf-8")
    assert "codex-subscription.json" in text
    assert "claude" not in text.lower()
    assert "EXECUTOR_PROFILE" not in text
    assert "benchmark readiness" in text
    assert "benchmark run" in text
    assert text.count("--execution-only") == 2
    assert 'export XDG_CONFIG_HOME="$DEV_VENV/.xdg/config"' in text
    assert 'export XDG_STATE_HOME="$DEV_VENV/.xdg/state"' in text
    assert 'export XDG_DATA_HOME="$DEV_VENV/.xdg/data"' in text
    assert "caller shell environment is unchanged" in text\n    assert "collect-value-smoke-evidence.py" in text
