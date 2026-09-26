from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "decision-study"


def _source_corpus() -> Path:
    return Path(
        str(
            files("agent_workflow_comparative_eval")
            .joinpath("resources")
            .joinpath("studies")
            .joinpath("routing-semantic-v1.corpus.json")
        )
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": sys.executable,
            "SOURCE_CORPUS": str(_source_corpus()),
            "DECISION_STUDY_ROOT": str(tmp_path / "decision-study"),
            "P1_ROOT": str(tmp_path / "decision-study" / "p1"),
            "P1_SAMPLE_SIZE": "3",
        }
    )
    return env


def test_decision_study_shell_scripts_have_valid_bash_syntax() -> None:
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


def test_decision_study_scripts_are_portable_and_executable() -> None:
    for path in sorted(SCRIPT_DIR.glob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/lump/" not in text, path
        if path.suffix == ".sh":
            mode = path.stat().st_mode
            assert mode & stat.S_IXUSR, path
            assert mode & stat.S_IXGRP, path
            assert mode & stat.S_IXOTH, path


def test_p1_prepare_selects_deterministic_subset_from_frozen_corpus(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    script = SCRIPT_DIR / "p1-prepare-smoke.sh"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    root = Path(env["P1_ROOT"])
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    corpus = json.loads((root / "corpus-smoke.json").read_text(encoding="utf-8"))
    assert selection["development_only"] is True
    assert selection["sample_size"] == 3
    assert len(selection["selected_case_ids"]) == 3
    assert [case["case_id"] for case in corpus["cases"]] == selection[
        "selected_case_ids"
    ]
    assert (
        selection["source_corpus_sha256"]
        == "e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280"
    )


def test_p1_verifier_checks_persisted_evidence_contract(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["P1_SAMPLE_SIZE"] = "1"
    prepare = subprocess.run(
        ["bash", str(SCRIPT_DIR / "p1-prepare-smoke.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert prepare.returncode == 0, prepare.stderr

    root = Path(env["P1_ROOT"])
    smoke = json.loads((root / "corpus-smoke.json").read_text(encoding="utf-8"))
    case = smoke["cases"][0]
    case_id = case["case_id"]
    run = root / "run"
    run.mkdir()

    request_id = f"req-{case_id}"
    manifest = {
        "oracle_seen_during_inference": False,
        "files": {
            "study_spec": "study-spec.json",
            "corpus": "corpus.json",
            "observations": "observations.jsonl",
            "provider_requests": "provider-requests.jsonl",
            "exclusions": "exclusions.jsonl",
        },
        "identity": {
            "question_set_version": "routing/v2",
            "projector_version": "routing-state/v2",
        },
        "counts": {
            "cases": 1,
            "observations": 3,
            "provider_requests": 1,
            "exclusions": 0,
        },
    }
    (run / "run-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (run / "study-spec.json").write_text("{}", encoding="utf-8")
    (run / "corpus.json").write_text(json.dumps(smoke), encoding="utf-8")
    (run / "exclusions.jsonl").write_text("", encoding="utf-8")

    request = {
        "request_id": request_id,
        "decisions": [
            "routing.task_class",
            "routing.interaction_required",
            "routing.semantic_risk",
        ],
        "status": "success",
        "usage": {
            "input_tokens": 20,
            "output_tokens": 3,
            "provider_total_tokens": 23,
        },
        "privacy": {
            "raw_content_stored": False,
            "secret_values_stored": False,
        },
    }
    (run / "provider-requests.jsonl").write_text(
        json.dumps(request) + "\n", encoding="utf-8"
    )

    rows = []
    specs = [
        (
            "routing.task-class/v1",
            "choice",
            {
                "implementation": 0.1,
                "diagnosis": 0.1,
                "review": 0.6,
                "documentation": 0.1,
                "other": 0.1,
            },
            None,
        ),
        ("routing.interaction-required/v1", "noul", {}, 0.4),
        (
            "routing.semantic-risk/v1",
            "score",
            {"0": 0.2, "1": 0.6, "2": 0.2},
            None,
        ),
    ]
    for feature_id, semantic_type, probabilities, probability in specs:
        rows.append(
            {
                "feature_id": feature_id,
                "mode": "static",
                "identity": {
                    "question_set_version": "routing/v2",
                    "projector_version": "routing-state/v2",
                },
                "input": {
                    "case_id": case_id,
                    "raw_input_persisted": False,
                },
                "privacy": {
                    "raw_content_stored": False,
                    "secret_values_stored": False,
                },
                "control": {"usage": {}},
                "candidate": {
                    "usage": {},
                    "result": {
                        "request_id": request_id,
                        "semantic_type": semantic_type,
                        "semantic_status": "success",
                        "probabilities": probabilities,
                        "probability": probability,
                    },
                },
            }
        )
    (run / "observations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    env["TYPESAFE_API_KEY"] = "test-secret-that-must-not-appear"
    result = subprocess.run(
        ["bash", str(SCRIPT_DIR / "p1-verify-smoke.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    verification = json.loads(
        (root / "verification.json").read_text(encoding="utf-8")
    )
    assert verification["status"] == "pass"
    assert verification["checks"]["oracle_absent_during_inference"] is True
    assert verification["checks"]["one_request_per_observed_case"] is True
    assert verification["checks"]["semantic_probability_evidence_persisted"] is True


def test_p1_all_orders_prepare_run_verify() -> None:
    text = (SCRIPT_DIR / "p1-all.sh").read_text(encoding="utf-8")
    positions = [
        text.index("p1-prepare-smoke.sh"),
        text.index("p1-run-smoke.sh"),
        text.index("p1-verify-smoke.sh"),
    ]
    assert positions == sorted(positions)


def test_p2_requires_p1_and_keeps_oracle_out_of_inference_command() -> None:
    run = (SCRIPT_DIR / "p2-run-full.sh").read_text(encoding="utf-8")
    report = (SCRIPT_DIR / "p2-report.sh").read_text(encoding="utf-8")
    assert "ds_verify_p1_passed" in run
    command_line = next(
        line
        for line in run.splitlines()
        if 'benchmark decision-study-run "$SOURCE_CORPUS"' in line
    )
    assert "ORACLE" not in command_line
    assert 'decision-study-report "$P2_RUN" "$FROZEN_ORACLE"' in report
