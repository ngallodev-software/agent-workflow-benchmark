from __future__ import annotations

from pathlib import Path
import os
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
AGENTIC = ROOT / "scripts" / "agentic-jev"
V2_PREFLIGHT = ROOT / "scripts" / "adjudication" / "v2-evidence-preflight.sh"


def test_agentic_jev_scripts_have_valid_bash_syntax() -> None:
    scripts = sorted(AGENTIC.glob("*.sh")) + [V2_PREFLIGHT]
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


def test_agentic_jev_scripts_are_portable_and_executable() -> None:
    scripts = sorted(AGENTIC.glob("*.sh")) + [V2_PREFLIGHT]
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "/lump/" not in text, script
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, script
        assert mode & stat.S_IXGRP, script
        assert mode & stat.S_IXOTH, script


def test_agentic_pilot_requires_runtime_lock_then_live_tool_qualification() -> None:
    env = (AGENTIC / "env.sh").read_text(encoding="utf-8")
    freeze = (AGENTIC / "p0-freeze-runtime.sh").read_text(encoding="utf-8")
    qualify = (AGENTIC / "p0-qualify-tool.sh").read_text(encoding="utf-8")
    run = (AGENTIC / "p1-run-pilot.sh").read_text(encoding="utf-8")

    assert "openai-api/codex-lb/gpt-6-luna" in env
    assert 'AGENTIC_JEV_REASONING_EFFORT="${AGENTIC_JEV_REASONING_EFFORT:-high}"' in env
    assert "AGENTIC_JEV_MODEL" in freeze
    assert "AGENTIC_JEV_REASONING_EFFORT" in freeze
    assert "create_agentic_jev_runtime_lock" in freeze
    assert "TYPESAFE_API_KEY" in qualify or "aj_require_typesafe_key" in qualify
    assert "run_agentic_jev_tool_qualification" in qualify
    assert "AGENTIC_JEV_QUALIFICATION" in run
    assert "run_agentic_jev_pilot" in run


def test_v2_preflight_is_explicitly_not_real_cohort_qualification() -> None:
    text = V2_PREFLIGHT.read_text(encoding="utf-8")
    assert "run_v2_evidence_preflight" in text
    assert "real_cohort_ready:" in text
    assert "blocking_reason:" in text
    assert "V2_ADJUDICATION_MODEL" in text



def test_agentic_env_preserves_model_args_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["AGENTIC_JEV_MODEL_ARGS_JSON"] = '{"responses_api":true}'
    result = subprocess.run(
        [
            "bash",
            "-lc",
            'source scripts/agentic-jev/env.sh; printf "%s" "$AGENTIC_JEV_MODEL_ARGS_JSON"',
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == '{"responses_api":true}'


def test_agentic_env_defaults_model_args_json_without_extra_brace(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env.pop("AGENTIC_JEV_MODEL_ARGS_JSON", None)
    result = subprocess.run(
        [
            "bash",
            "-lc",
            'source scripts/agentic-jev/env.sh; printf "%s" "$AGENTIC_JEV_MODEL_ARGS_JSON"',
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == '{"responses_api":true}'
