from __future__ import annotations

from pathlib import Path
import json
import os
import stat
import subprocess
import sys

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
    archive = (AGENTIC / "p0-archive-attempt.sh").read_text(encoding="utf-8")
    freeze = (AGENTIC / "p0-freeze-runtime.sh").read_text(encoding="utf-8")
    qualify = (AGENTIC / "p0-qualify-tool.sh").read_text(encoding="utf-8")
    run = (AGENTIC / "p1-run-pilot.sh").read_text(encoding="utf-8")

    assert "openai-api/codex-lb/gpt-6-luna" in env
    assert 'AGENTIC_JEV_REASONING_EFFORT="${AGENTIC_JEV_REASONING_EFFORT:-high}"' in env
    assert "AGENTIC_JEV_ARCHIVE_ROOT" in env
    assert "AGENTIC_JEV_ARCHIVE_PASSING" in archive
    assert "pilot-run evidence already exists" in archive
    assert "archive target already exists" in archive
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



def test_agentic_qualification_requires_clean_evidence_root() -> None:
    text = (
        ROOT / "src" / "agent_workflow_benchmark" / "benchmarking" / "agentic_jev.py"
    ).read_text(encoding="utf-8")
    assert "qualification evidence directory is not empty" in text
    assert "preserve/archive the prior attempt before retrying" in text



def _agentic_archive_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    root = tmp_path / "agentic-jev-pilot-v1"
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": sys.executable,
            "AGENTIC_JEV_ROOT": str(root),
            "AGENTIC_JEV_RUNTIME_LOCK": str(root / "runtime-lock.json"),
            "AGENTIC_JEV_ARCHIVE_ROOT": str(root / "archive"),
            "AGENTIC_JEV_QUAL_ROOT": str(root / "tool-qualification"),
            "AGENTIC_JEV_QUALIFICATION": str(root / "tool-qualification" / "qualification.json"),
            "AGENTIC_JEV_RUN": str(root / "pilot-run"),
        }
    )
    return env, root


def test_agentic_phase0_archive_preserves_failed_attempt_before_cleanup(
    tmp_path: Path,
) -> None:
    env, root = _agentic_archive_env(tmp_path)
    root.mkdir(parents=True)
    lock = root / "runtime-lock.json"
    lock.write_text('{"lock":"failed-attempt"}\n', encoding="utf-8")
    qual = root / "tool-qualification"
    qual.mkdir()
    (qual / "qualification.json").write_text(
        json.dumps({"qualified": False}) + "\n",
        encoding="utf-8",
    )
    (qual / "inspect.log").write_text("private evidence\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(AGENTIC / "p0-archive-attempt.sh"), "failed-contract"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    target = root / "archive" / "failed-contract"
    assert target.is_dir()
    assert not lock.exists()
    assert not qual.exists()
    assert (target / "runtime-lock.json").read_text(encoding="utf-8") == (
        '{"lock":"failed-attempt"}\n'
    )
    assert (target / "tool-qualification" / "inspect.log").is_file()
    manifest = json.loads(
        (target / "archive-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["label"] == "failed-contract"
    assert manifest["sources"]["qualification"]["qualified"] is False
    assert len(manifest["sources"]["runtime_lock"]["sha256"]) == 64


def test_agentic_phase0_archive_refuses_current_passing_qualification(
    tmp_path: Path,
) -> None:
    env, root = _agentic_archive_env(tmp_path)
    root.mkdir(parents=True)
    lock = root / "runtime-lock.json"
    lock.write_text('{"lock":"passing"}\n', encoding="utf-8")
    qual = root / "tool-qualification"
    qual.mkdir()
    (qual / "qualification.json").write_text(
        json.dumps({"qualified": True}) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(AGENTIC / "p0-archive-attempt.sh"), "do-not-archive"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "refusing to archive a passing Phase-0 qualification" in result.stderr
    assert lock.is_file()
    assert qual.is_dir()
    assert not (root / "archive" / "do-not-archive").exists()


def test_agentic_phase0_archive_allows_explicitly_superseded_pass(
    tmp_path: Path,
) -> None:
    env, root = _agentic_archive_env(tmp_path)
    env["AGENTIC_JEV_ARCHIVE_PASSING"] = "1"
    root.mkdir(parents=True)
    (root / "runtime-lock.json").write_text('{"lock":"old"}\n', encoding="utf-8")
    qual = root / "tool-qualification"
    qual.mkdir()
    (qual / "qualification.json").write_text(
        json.dumps({"qualified": True}) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(AGENTIC / "p0-archive-attempt.sh"), "superseded-runtime"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (
            root
            / "archive"
            / "superseded-runtime"
            / "archive-manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["sources"]["qualification"]["qualified"] is True



def test_external_eval_scout_is_pinned_and_answer_blind_in_manager_selection() -> None:
    selector = (AGENTIC / "p2-select-external-cohort.py").read_text(encoding="utf-8")
    freeze = (AGENTIC / "p2-freeze-external-cohort.sh").read_text(encoding="utf-8")

    assert "b49df6bc9e30b2d24571084bc710b9439b9ffa77" in selector
    assert "b316c349947c29963fce3f4a65967c9807a4b673" in selector
    assert "b49df6bc9e30b2d24571084bc710b9439b9ffa77" in freeze
    assert 'required = {"question_id", "variant", "set", "title"}' in selector
    assert 'row["manager_data"]' not in selector
    assert 'row["correct_proposal_id"]' not in selector
    assert 'row["patch"]' not in selector
    assert 'row["test_patch"]' not in selector


def test_external_eval_selector_freezes_six_manager_and_six_swebench_tasks(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "inspect_evals"
    data = (
        checkout
        / "src"
        / "inspect_evals"
        / "swe_lancer"
        / "data"
    )
    data.mkdir(parents=True)
    csv_path = data / "all_swelancer_tasks.csv"
    rows = [
        "question_id,variant,price,price_limit,manager_data,manager_commit,acceptable_folders,cwd,set,title,description,proposals"
    ]
    for i in range(10):
        rows.append(
            f"manager-{i},swe_manager,1,1,SECRET_CORRECT_{i},,,/app,diamond,"
            f"Manager task {i},Description {i},Proposals {i}"
        )
    rows.append(
        "ic-1,ic_swe,1,1,SECRET_IC,,,/app,diamond,IC task,Description,Proposals"
    )
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    prior = tmp_path / "run-manifest.json"
    prior.write_text(
        json.dumps(
            {
                "study_id": "agentic-jev-pilot-v1",
                "arms": {
                    "C-skill-plus-jev": {
                        "samples": 24,
                        "jev_tool_calls": 0,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "cohort.json"

    result = subprocess.run(
        [
            sys.executable,
            str(AGENTIC / "p2-select-external-cohort.py"),
            str(checkout),
            str(output),
            str(prior),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    manager = manifest["cohorts"]["swe_lancer_manager_choice"]
    swebench = manifest["cohorts"]["swe_bench_semantic_ambiguity"]
    assert len(manager) == 6
    assert len(swebench) == 6
    assert manifest["selection_contract"]["gold_fields_used_for_selection"] is False
    assert manifest["execution_gate"]["first_run"] == "C-skill-plus-jev only"
    assert all("SECRET_CORRECT" not in json.dumps(item) for item in manager)



def test_external_eval_prepare_preserves_frozen_runtime_versions() -> None:
    prepare = (AGENTIC / "p2-prepare-external-evals.sh").read_text(encoding="utf-8")
    assert "inspect-ai==0.3.268" in prepare
    assert "inspect-swe==0.2.71" in prepare
    assert "typesafe-sdk==0.6.0" in prepare
    assert "load_agentic_jev_runtime_lock" in prepare
    assert "p2-freeze-external-cohort.sh first" in prepare


def test_external_eval_c_runner_is_uptake_only_and_sample_scoped() -> None:
    runner = (
        ROOT
        / "src"
        / "agent_workflow_benchmark"
        / "benchmarking"
        / "agentic_jev_external.py"
    ).read_text(encoding="utf-8")
    shell = (AGENTIC / "p2-run-external-c.sh").read_text(encoding="utf-8")

    assert 'arm_id="C-skill-plus-jev"' in runner
    assert "sample_id=[sample_id]" in runner
    assert "score=False" in runner
    assert 'max_samples=1' in runner
    assert '"scoring_enabled": False' in runner
    assert "sample-result.json" in runner
    assert "run_external_jev_scout" in shell
    assert "aj_require_typesafe_key" in shell


def test_external_eval_runner_does_not_modify_frozen_host_tool_module() -> None:
    external = (
        ROOT
        / "src"
        / "agent_workflow_benchmark"
        / "benchmarking"
        / "agentic_jev_external.py"
    ).read_text(encoding="utf-8")
    assert "from .agentic_jev import" in external
    assert "build_agentic_jev_solver" in external
    assert "jev_bridged_tool(" not in external


def test_external_eval_schemas_are_registered() -> None:
    from agent_workflow_benchmark.benchmarking.schema_contracts import validate_instance

    validate_instance(
        {
            "schema": "agent-workflow-benchmark/agentic-jev-external-eval-cohort/v1",
            "study_id": "agentic-jev-external-eval-scout-v1",
            "development_only": True,
            "lineage": {},
            "sources": {},
            "selection_contract": {},
            "cohorts": {
                "swe_lancer_manager_choice": [{} for _ in range(6)],
                "swe_bench_semantic_ambiguity": [{} for _ in range(6)],
            },
            "execution_gate": {},
            "claim_boundary": {},
        },
        "agent-workflow-benchmark/agentic-jev-external-eval-cohort/v1",
    )
