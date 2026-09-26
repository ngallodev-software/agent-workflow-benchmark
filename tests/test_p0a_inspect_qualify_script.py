from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


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


def _run_dispute_requires_c(tmp_path: Path, cases: list[dict[str, object]]) -> str:
    dispute = tmp_path / "dispute.json"
    dispute.write_text(
        __import__("json").dumps({"cases": cases}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": __import__("sys").executable,
            "DISPUTE_VIEW": str(dispute),
        }
    )
    command = r"""
source scripts/adjudication/lib.sh
aw_dispute_requires_c
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
    return result.stdout.strip()


def test_dispute_view_requires_c_when_cases_are_present(tmp_path: Path) -> None:
    assert _run_dispute_requires_c(
        tmp_path,
        [{"case_id": "case-001", "disputed_decision_ids": ["routing.task_class"]}],
    ) == "true"


def test_dispute_view_skips_c_only_when_cases_are_empty(tmp_path: Path) -> None:
    assert _run_dispute_requires_c(tmp_path, []) == "false"


def test_internal_script_chaining_does_not_require_execute_bits() -> None:
    for name in ("p0a-qualify.sh", "p0b-run-ab.sh", "p0b-run-c.sh", "run-all.sh"):
        text = (SCRIPT_DIR / name).read_text(encoding="utf-8")
        for child in (
            "verify-qualification.sh",
            "verify-frozen-inputs.sh",
            "p0a-qualify.sh",
            "p0b-run-ab.sh",
            "p0b-validate-ab.sh",
            "p0b-compute-disputes.sh",
            "p0b-run-c.sh",
            "p0b-prepare-resolutions.sh",
            "p0b-freeze.sh",
            "p0b-validate-oracle.sh",
        ):
            if child in text:
                assert f'bash "$SCRIPT_DIR/{child}"' in text


def test_adjudication_shell_scripts_are_committed_executable() -> None:
    for script in sorted(SCRIPT_DIR.glob("*.sh")):
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, f"{script} is not executable by owner"
        assert mode & stat.S_IXGRP, f"{script} is not executable by group"
        assert mode & stat.S_IXOTH, f"{script} is not executable by others"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_resolutions_emits_only_genuine_three_way_conflicts(
    tmp_path: Path,
) -> None:
    oracle_run = tmp_path / "oracle-run"
    (oracle_run / "a" / "output").mkdir(parents=True)
    (oracle_run / "b" / "output").mkdir(parents=True)
    (oracle_run / "c" / "output").mkdir(parents=True)

    authoring = tmp_path / "authoring.json"
    authoring.write_text(
        json.dumps(
            {
                "study_id": "routing-semantic-v1",
                "dataset_version": "routing-semantic-corpus-v1.0.0",
                "decision_seams": [
                    {
                        "decision_id": "routing.semantic_risk",
                        "oracle_type": "ordinal",
                        "levels": [0, 1, 2],
                    }
                ],
                "cases": [
                    {
                        "case_id": "rsv1-050",
                        "task": "Synthetic semantic-risk conflict",
                        "metadata": {"fixture": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dispute = oracle_run / "oracle-disputes-for-c.json"
    dispute.write_text(
        json.dumps(
            {
                "source_authoring_view_sha256": _sha256(authoring),
                "protocol_version": "routing-semantic-oracle-v1.0.0",
                "cases": [
                    {
                        "case_id": "rsv1-050",
                        "disputed_decision_ids": ["routing.semantic_risk"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def write_pass(path: Path, input_sha: str, label: int) -> None:
        path.write_text(
            json.dumps(
                {
                    "input_view_sha256": input_sha,
                    "records": [
                        {
                            "case_id": "rsv1-050",
                            "labels": {"routing.semantic_risk": label},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_pass(
        oracle_run / "a" / "output" / "adjudication.json",
        _sha256(authoring),
        0,
    )
    write_pass(
        oracle_run / "b" / "output" / "adjudication.json",
        _sha256(authoring),
        1,
    )
    write_pass(
        oracle_run / "c" / "output" / "adjudication.json",
        _sha256(dispute),
        2,
    )

    resolutions = oracle_run / "resolutions.json"
    review = oracle_run / "resolution-review.json"
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": sys.executable,
            "PRIVATE_ROOT": str(tmp_path / "private"),
            "ORACLE_RUN": str(oracle_run),
            "ORACLE_VIEW": str(authoring),
            "DISPUTE_VIEW": str(dispute),
            "RESOLUTIONS": str(resolutions),
            "RESOLUTION_REVIEW": str(review),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_DIR / "p0b-prepare-resolutions.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    resolution_value = json.loads(resolutions.read_text(encoding="utf-8"))
    assert resolution_value["records"] == [
        {
            "case_id": "rsv1-050",
            "decision_id": "routing.semantic_risk",
            "status": "unresolved",
            "rationale": (
                "TODO: record the adjudication rationale for this "
                "three-way conflict."
            ),
            "participants": [],
        }
    ]

    review_value = json.loads(review.read_text(encoding="utf-8"))
    conflict = review_value["three_way_conflicts"][0]
    assert conflict["votes"] == {"a": 0, "b": 1, "c": 2}
    assert conflict["allowed_labels"] == [0, 1, 2]
    assert conflict["task"] == "Synthetic semantic-risk conflict"
    assert conflict["oracle_question"] == (
        "What is the consequence of acting on a materially wrong interpretation "
        "of this request?"
    )

    markdown = oracle_run / "resolution-review.md"
    rendered = markdown.read_text(encoding="utf-8")
    assert "### Verbatim case prompt" in rendered
    assert "> Synthetic semantic-risk conflict" in rendered
    assert "### Question you are deciding" in rendered
    assert (
        "What is the consequence of acting on a materially wrong interpretation "
        "of this request?"
    ) in rendered
    assert "**A:** `0`" in rendered
    assert "**B:** `1`" in rendered
    assert "**C:** `2`" in rendered
    assert "oracle_eligible" in rendered


def test_freeze_script_gates_unreviewed_three_way_resolution_templates() -> None:
    text = (SCRIPT_DIR / "p0b-freeze.sh").read_text(encoding="utf-8")
    assert "p0b-prepare-resolutions.sh" in text
    assert "TODO rationale text" in text
    assert "ALLOW_UNRESOLVED_RESOLUTIONS" in text


def test_master_runner_includes_three_way_resolution_stage() -> None:
    text = (SCRIPT_DIR / "run-all.sh").read_text(encoding="utf-8")
    assert text.index("p0b-run-c.sh") < text.index("p0b-prepare-resolutions.sh")
    assert text.index("p0b-prepare-resolutions.sh") < text.index("p0b-freeze.sh")


def test_existing_machine_review_can_be_rendered_without_regeneration(
    tmp_path: Path,
) -> None:
    oracle_run = tmp_path / "oracle-run"
    oracle_run.mkdir()
    review = oracle_run / "resolution-review.json"
    review.write_text(
        json.dumps(
            {
                "study_id": "routing-semantic-v1",
                "dataset_version": "routing-semantic-corpus-v1.0.0",
                "three_way_conflicts": [
                    {
                        "case_id": "rsv1-050",
                        "decision_id": "routing.semantic_risk",
                        "task": (
                            "Identify which repository artifacts are suitable "
                            "for a public case study and which should remain private."
                        ),
                        "metadata": {
                            "change_scope": "analysis-only",
                            "environment": "repository",
                            "risk": "low",
                        },
                        "decision_seam": {
                            "decision_id": "routing.semantic_risk",
                            "oracle_type": "ordinal",
                            "levels": [0, 1, 2],
                            "level_meaning": {
                                "0": "low consequence; easily reversible",
                                "1": "moderate consequence; careful verification required",
                                "2": (
                                    "high consequence; authority, security, or "
                                    "irreversible-state risk"
                                ),
                            },
                        },
                        "allowed_labels": [0, 1, 2],
                        "votes": {"a": 1, "b": 0, "c": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    markdown = oracle_run / "resolution-review.md"
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": sys.executable,
            "PRIVATE_ROOT": str(tmp_path / "private"),
            "ORACLE_RUN": str(oracle_run),
            "RESOLUTION_REVIEW": str(review),
            "RESOLUTION_REVIEW_MD": str(markdown),
            "ORACLE_REVIEW_GUIDE": "",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_DIR / "p0b-render-resolution-review.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    rendered = markdown.read_text(encoding="utf-8")
    assert (
        "> Identify which repository artifacts are suitable for a public case "
        "study and which should remain private."
    ) in rendered
    assert "**A:** `1`" in rendered
    assert "**B:** `0`" in rendered
    assert "**C:** `2`" in rendered
    assert "Metadata is supporting evidence only." in rendered


def test_resolution_review_docs_explain_oracle_eligible() -> None:
    readme = (SCRIPT_DIR / "README.md").read_text(encoding="utf-8")
    assert (
        "`oracle_eligible` says which oracle questions require labels" in readme
    )
    assert "not an answer key" in readme
    assert "routing-semantic-v1-oracle-review-guide.md" in readme
