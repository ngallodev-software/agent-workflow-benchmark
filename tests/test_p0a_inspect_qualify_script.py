from __future__ import annotations

import os
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

    assert "Existing passing P0A qualification found; verifying without regenerating it." in text

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


def test_adjudication_scripts_do_not_hardcode_local_install_root() -> None:
    for path in sorted(SCRIPT_DIR.glob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/lump/" not in text, path

    operator = (ROOT / "docs" / "INSPECT_ORACLE_ADJUDICATION.md").read_text(
        encoding="utf-8"
    )
    assert "/lump/" not in operator


def test_env_derives_benchmark_repo_from_script_location_and_honors_overrides(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    env = os.environ.copy()
    env.update(
        {
            "AW": "/portable/venv/bin/agent-workflow",
            "PYTHON": "/portable/venv/bin/python",
            "COMP_REPO": "/portable/agent-workflow-comparative-eval",
            "PRIVATE_ROOT": str(private_root),
        }
    )
    command = r"""
source scripts/adjudication/env.sh
printf '%s\n' "$BENCH_REPO" "$AW" "$PYTHON" "$COMP_REPO" "$PRIVATE_ROOT"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    values = result.stdout.splitlines()
    assert values == [
        str(ROOT),
        "/portable/venv/bin/agent-workflow",
        "/portable/venv/bin/python",
        "/portable/agent-workflow-comparative-eval",
        str(private_root),
    ]


def test_recovery_command_is_documented_with_runtime_lock_preservation() -> None:
    readme = (SCRIPT_DIR / "README.md").read_text(encoding="utf-8")
    operator = (ROOT / "docs" / "INSPECT_ORACLE_ADJUDICATION.md").read_text(
        encoding="utf-8"
    )
    command = "FORCE_REQUALIFY=1 MODEL_ID=deepseek-flash"
    for text in (readme, operator):
        assert command in text
        assert "runtime lock" in text.lower()
        assert "verify-qualification.sh" in text
