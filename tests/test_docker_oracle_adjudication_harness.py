from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import agent_workflow_comparative_eval as comparative
import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts" / "prepare-docker-oracle-adjudication.py"
RUNNER_PATH = ROOT / "scripts" / "run-docker-oracle-adjudication.sh"


def _helper():
    spec = importlib.util.spec_from_file_location("docker_adjudication_helper", HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_model_schema_is_bound_to_all_frozen_cases_and_seams():
    helper = _helper()
    view = comparative.oracle_authoring_view(
        comparative.load_study_corpus("routing-semantic-v1")
    )
    records = helper.expected_records(view)
    schema = helper.model_output_schema(records)

    assert len(records) == 120
    assert sum(len(item["decision_ids"]) for item in records) == 360
    assert schema["properties"]["records"]["minItems"] == 120
    assert schema["properties"]["records"]["maxItems"] == 120

    item = schema["properties"]["records"]["items"]
    assert len(item["properties"]["case_id"]["enum"]) == 120
    assert item["properties"]["labels"]["required"] == [
        "routing.task_class",
        "routing.interaction_required",
        "routing.semantic_risk",
    ]


def test_prepare_agent_writes_private_prompt_schema_and_hash_bound_metadata(tmp_path: Path):
    helper = _helper()
    view = comparative.oracle_authoring_view(
        comparative.load_study_corpus("routing-semantic-v1")
    )
    view_path = tmp_path / "view.json"
    protocol_path = tmp_path / "protocol.md"
    view_path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    protocol_path.write_text("# Frozen protocol\n", encoding="utf-8")

    result = helper.prepare_agent(
        destination=tmp_path / "a",
        view_path=view_path,
        protocol_path=protocol_path,
        adjudicator_id="codex-a",
    )

    input_dir = tmp_path / "a" / "input"
    metadata = json.loads((input_dir / "pass-metadata.json").read_text(encoding="utf-8"))
    prompt = (input_dir / "START_PROMPT.md").read_text(encoding="utf-8")

    assert result["cases"] == 120
    assert result["labels"] == 360
    assert metadata["adjudicator_id"] == "codex-a"
    assert metadata["input_view_sha256"] == helper.sha256_file(view_path)
    assert len(metadata["expected_records"]) == 120
    assert "codex-a" in prompt
    assert "TypeSafe/Jev output" in prompt
    assert (input_dir / "model-output.schema.json").is_file()


def test_prepare_c_shape_uses_only_disputed_seams():
    helper = _helper()
    view = {
        "schema": "agent-workflow-benchmark/decision-study-oracle-dispute-view/v1",
        "study_id": helper.STUDY_ID,
        "dataset_version": helper.DATASET_VERSION,
        "protocol_version": helper.PROTOCOL_VERSION,
        "cases": [
            {
                "case_id": "case-001",
                "task": "Example",
                "metadata": {},
                "oracle_eligible": {
                    "routing.task_class": True,
                    "routing.interaction_required": True,
                    "routing.semantic_risk": True,
                },
                "disputed_decision_ids": [
                    "routing.task_class",
                    "routing.semantic_risk",
                ],
            }
        ],
    }
    records = helper.expected_records(view)
    assert records == [
        {
            "case_id": "case-001",
            "decision_ids": ["routing.task_class", "routing.semantic_risk"],
        }
    ]


def test_adjudicator_codex_config_rejects_context_expanding_features(tmp_path: Path):
    helper = _helper()
    good = tmp_path / "good.toml"
    good.write_text(
        'model_provider = "load-balancer"\n'
        '[model_providers.load-balancer]\n'
        'base_url = "https://example.invalid/v1"\n'
        'env_key = "CODEX_PROXY_TOKEN"\n',
        encoding="utf-8",
    )
    helper.validate_codex_config(argparse.Namespace(config=good))

    bad = tmp_path / "bad.toml"
    bad.write_text(
        'model_provider = "load-balancer"\n'
        '[mcp_servers.extra]\n'
        'url = "https://example.invalid/mcp"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="not permitted"):
        helper.validate_codex_config(argparse.Namespace(config=bad))


def test_docker_adjudication_runner_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", str(RUNNER_PATH)], check=True)


def test_container_runtime_does_not_copy_repository_or_accept_typesafe_credentials():
    dockerfile = (ROOT / "docker" / "adjudication" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    entrypoint = (ROOT / "docker" / "adjudication" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )

    copy_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("COPY ")
    ]
    assert copy_lines == [
        "COPY docker/adjudication/entrypoint.sh /usr/local/bin/aw-adjudicate",
        "COPY docker/adjudication/wrap-output.mjs /opt/aw-adjudication/wrap-output.mjs",
    ]
    assert "ARG CODEX_VERSION=latest" in dockerfile
    runner = RUNNER_PATH.read_text(encoding="utf-8")
    assert 'CODEX_VERSION="${CODEX_VERSION:-latest}"' in runner
    assert "TYPESAFE_" in entrypoint
    assert "refusing adjudicator startup" in entrypoint
    assert "--sandbox read-only" in entrypoint
    assert 'web_search="disabled"' in entrypoint
