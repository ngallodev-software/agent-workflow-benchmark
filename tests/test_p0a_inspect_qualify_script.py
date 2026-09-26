from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "adjudication"
P0A = SCRIPT_DIR / "p0a-qualify.sh"


def test_adjudication_shell_scripts_have_valid_bash_syntax() -> None:
    scripts = sorted(SCRIPT_DIR.glob("*.sh"))
    assert scripts
    for script in scripts:
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_p0a_defaults_to_deepseek_and_explicitly_passes_selected_model() -> None:
    text = P0A.read_text(encoding="utf-8")

    assert 'MODEL_ID="${MODEL_ID:-deepseek-flash}"' in text
    assert 'ADJUDICATION_MODEL="openai-api/codex-lb/$MODEL_ID"' in text
    assert '--model "$ADJUDICATION_MODEL"' in text
    assert "FORCE_REQUALIFY" in text
    assert "The runtime lock should remain in place" in text


def test_p0a_preserves_runtime_lock_across_requalification() -> None:
    text = P0A.read_text(encoding="utf-8")

    assert 'if [[ -f "$RUNTIME_LOCK" ]]; then' in text
    assert "Reusing frozen runtime lock" in text
    assert 'rm -f "$RUNTIME_LOCK"' not in text
    assert 'rm -rf "$PRIVATE_ROOT"' not in text


def test_environment_uses_non_secret_inspect_provider_sentinel() -> None:
    text = (SCRIPT_DIR / "env.sh").read_text(encoding="utf-8")

    assert 'CODEX_LB_API_KEY="${CODEX_LB_API_KEY:-inspect-placeholder}"' in text
    assert "codex-lb itself does not require this credential" in text


def test_p0b_ab_runner_verifies_before_real_execution() -> None:
    text = (SCRIPT_DIR / "p0b-run-ab.sh").read_text(encoding="utf-8")

    qualification = text.index('verify-qualification.sh')
    resolve_model = text.index("aw_resolve_adjudication_model")
    frozen = text.index('verify-frozen-inputs.sh')
    run_primary = text.index("adjudication-inspect-run-primary")

    assert qualification < resolve_model < frozen < run_primary
    assert "deepseek-flash" not in text


def test_p0b_model_is_resolved_from_qualification() -> None:
    text = (SCRIPT_DIR / "lib.sh").read_text(encoding="utf-8")

    assert 'gates.get("IA-2", {})' in text
    assert 'export ADJUDICATION_MODEL="$qualified_model"' in text
    assert "MODEL_ID selects" in text
    assert "ADJUDICATION_MODEL=" in text
    assert "but P0A qualified" in text


def test_master_runner_preserves_existing_p0a_and_orders_p0b_steps() -> None:
    text = (SCRIPT_DIR / "run-all.sh").read_text(encoding="utf-8")

    assert "Existing P0A qualification found; verifying without regenerating it." in text

    ordered = [
        "p0b-run-ab.sh",
        "p0b-validate-ab.sh",
        "p0b-compute-disputes.sh",
        "p0b-run-c.sh",
        "p0b-freeze.sh",
        "p0b-validate-oracle.sh",
    ]
    positions = [text.index(item) for item in ordered]
    assert positions == sorted(positions)
