from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from agent_workflow_benchmark.benchmarking.scoring_bundle_tools import (
    initialize_scoring_bundle,
    validate_scoring_bundle,
)
from agent_workflow_benchmark.benchmarking.universal_scoring import (
    BundleRunner,
    run_dimension,
)


def _contract(*dimensions: tuple[str, str, float]) -> dict:
    return {
        "dimensions": [
            {
                "id": dimension,
                "max_points": points,
                "checks": [
                    {
                        "id": check,
                        "max_points": points,
                        "partial_credit": "proportional",
                        "evidence_reference": f"external://score.py#{check}",
                    }
                ],
            }
            for dimension, check, points in dimensions
        ]
    }


def test_scoring_bundle_init_and_validate(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    created = initialize_scoring_bundle(destination)
    assert Path(created["score"]).is_file()
    assert (destination / "bundle.json").is_file()
    observed = validate_scoring_bundle(destination)
    assert observed["bundle_id"] == "replace-me"
    assert "semantic-core" in observed["probes"]


def test_command_json_probe_scores_contract_check(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    worktree = tmp_path / "worktree"
    scores = worktree / ".awb" / "scores"
    bundle.mkdir()
    worktree.mkdir()
    scores.mkdir(parents=True)
    (worktree / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    probe = bundle / "probe.py"
    probe.write_text(
        "import argparse, json\n"
        "p=argparse.ArgumentParser(); p.add_argument('--output'); a=p.parse_args()\n"
        "open(a.output,'w',encoding='utf-8').write(json.dumps({'fraction':0.75}))\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "agent-workflow/universal-scoring-bundle/v1",
        "bundle_id": "command-test",
        "version": "1",
        "parameters": {"threshold": 3},
        "probes": {
            "tests": {
                "kind": "command",
                "argv": [sys.executable, "{bundle}/probe.py", "--output", "{probe_result}"],
                "result_mode": "json-file",
            }
        },
        "dimensions": {
            "quality": {
                "contract_checks": {
                    "quality-check": {
                        "components": [
                            {
                                "id": "tests",
                                "probe": "tests",
                                "weight": 1,
                                "value": {"path": "/payload/fraction", "mode": "fraction"},
                            }
                        ]
                    }
                }
            }
        },
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    contract = _contract(("quality", "quality-check", 10.0))
    contract_path = bundle / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    result = scores / "quality.json"

    value = run_dimension(bundle, worktree, result, "quality", 10.0, contract_path)
    assert value["earned_points"] == 7.5
    assert value["checks"][0]["partial_credit"] is True


def test_typesafe_batch_is_single_request_with_many_questions(tmp_path: Path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    worktree = tmp_path / "worktree"
    scores = worktree / ".awb" / "scores"
    bundle.mkdir()
    worktree.mkdir()
    scores.mkdir(parents=True)
    (worktree / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    calls = {"count": 0, "question_count": 0}

    class FakeScore:
        def __init__(self, *, instructions, criteria):
            self.instructions = instructions
            self.criteria = criteria

    class FakeAnswer:
        score = 3.0
        confidence = 0.9
        probabilities = {"0": 0.0, "1": 0.0, "2": 0.1, "3": 0.8, "4": 0.1}

    class FakeUsage:
        input_tokens = 100
        output_tokens = 20

    class FakeResponse:
        model = "fake-model"
        request_id = "request-1"
        usage = FakeUsage()

        def __init__(self, questions):
            self.scores = {key: FakeAnswer() for key in questions}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def system_one(self, *, state, questions):
            calls["count"] += 1
            calls["question_count"] = len(questions)
            assert state["source_files"][0]["path"] == "app.py"
            return FakeResponse(questions)

    fake = types.ModuleType("typesafe_sdk")
    fake.Score = FakeScore
    fake.TypeSafeClient = FakeClient
    fake.TypeSafeError = RuntimeError
    monkeypatch.setitem(sys.modules, "typesafe_sdk", fake)

    criteria = ["0", "1", "2", "3", "4"]
    manifest = {
        "schema": "agent-workflow/universal-scoring-bundle/v1",
        "bundle_id": "typesafe-test",
        "version": "1",
        "probes": {
            "semantic": {
                "kind": "typesafe-batch",
                "context": {"worktree_globs": ["**/*.py"]},
                "questions": [
                    {"id": "correctness", "instructions": "Score correctness.", "criteria": criteria},
                    {"id": "maintainability", "instructions": "Score maintainability.", "criteria": criteria},
                    {"id": "task_fit", "instructions": "Score task fit.", "criteria": criteria},
                ],
            }
        },
        "dimensions": {
            "quality": {
                "contract_checks": {
                    "quality-check": {
                        "components": [
                            {
                                "id": "correctness",
                                "probe": "semantic",
                                "weight": 2,
                                "value": {"path": "/answers/correctness/score", "mode": "linear", "min": 0, "max": 4},
                            },
                            {
                                "id": "maintainability",
                                "probe": "semantic",
                                "weight": 1,
                                "value": {"path": "/answers/maintainability/score", "mode": "linear", "min": 0, "max": 4},
                            },
                        ]
                    }
                }
            }
        },
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    runner = BundleRunner(bundle, worktree, scores / "quality.json")
    result = runner.score_dimension("quality", 10.0, _contract(("quality", "quality-check", 10.0)))
    assert result["earned_points"] == 7.5
    assert calls == {"count": 1, "question_count": 3}


def test_llm_command_prompt_and_json_response(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    worktree = tmp_path / "worktree"
    scores = worktree / ".awb" / "scores"
    bundle.mkdir()
    worktree.mkdir()
    scores.mkdir(parents=True)
    (worktree / "README.md").write_text("# Sample\n", encoding="utf-8")
    adapter = bundle / "llm.py"
    adapter.write_text(
        "import json, sys\n"
        "prompt=sys.stdin.read()\n"
        "assert 'Evaluation context JSON follows' in prompt\n"
        "print(json.dumps({'rating':8,'note':'ok'}))\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "agent-workflow/universal-scoring-bundle/v1",
        "bundle_id": "llm-test",
        "version": "1",
        "parameters": {"audience": "reviewer"},
        "probes": {
            "llm": {
                "kind": "llm-command",
                "argv": [sys.executable, "{bundle}/llm.py"],
                "prompt": "Evaluate the supplied implementation and return JSON.",
                "response_mode": "json-stdout",
                "context": {"worktree_globs": ["README.md"]},
            }
        },
        "dimensions": {
            "quality": {
                "contract_checks": {
                    "quality-check": {
                        "components": [
                            {
                                "id": "llm-rating",
                                "probe": "llm",
                                "weight": 1,
                                "value": {"path": "/payload/rating", "mode": "linear", "min": 0, "max": 10},
                            }
                        ]
                    }
                }
            }
        },
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = run_dimension(
        bundle,
        worktree,
        scores / "quality.json",
        "quality",
        10.0,
        _write_contract(bundle, _contract(("quality", "quality-check", 10.0))),
    )
    assert result["earned_points"] == 8.0


def _write_contract(bundle: Path, value: dict) -> Path:
    path = bundle / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path
