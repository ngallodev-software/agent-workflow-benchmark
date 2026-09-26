from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p0a-inspect-qualify.sh"


def test_p0a_launcher_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_p0a_launcher_fixes_current_adjudication_model() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'MODEL_ID="gpt-6-luna"' in text
    assert 'ADJUDICATION_MODEL="openai-api/codex-lb/$MODEL_ID"' in text
    assert "--model \"$ADJUDICATION_MODEL\"" in text
    assert "--model-arg responses_api=true" in text
    assert ".codex/config.toml" in text  # present only in the non-inference warning
    assert "tomllib" not in text


def test_p0a_launcher_preserves_runtime_lock_across_retries() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'if [[ -f "$RUNTIME_LOCK" ]]; then' in text
    assert 'Reusing frozen cohort runtime lock' in text
    assert 'mv "$QUALIFICATION_ROOT"' in text
    assert 'mv "$QUALIFICATION"' in text
    assert 'rm -f "$RUNTIME_LOCK"' not in text
    assert 'rm -rf "$PRIVATE_ROOT"' not in text


def test_p0a_launcher_uses_non_secret_inspect_provider_sentinel() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"' in text
    assert "not a credential" in text
