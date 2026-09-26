from __future__ import annotations

import json
from pathlib import Path

import agent_workflow_comparative_eval as comparative
import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking import inspect_adjudication as inspect_runtime
from agent_workflow_benchmark.benchmarking.adjudication_module import (
    ABC_ADJUDICATION_MODULE_SCHEMA_V2,
    validate_abc_adjudication_module,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = (
    ROOT
    / "modules"
    / "abc-adjudication"
    / "routing-semantic-v1.inspect.module.json"
)


def _authoring_view(tmp_path: Path) -> Path:
    view = comparative.oracle_authoring_view(
        comparative.load_study_corpus("routing-semantic-v1")
    )
    path = tmp_path / "oracle-view.json"
    path.write_text(
        json.dumps(view, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _valid_output(view_path: Path) -> dict:
    view = json.loads(view_path.read_text(encoding="utf-8"))
    return {
        "records": [
            {
                "case_id": case["case_id"],
                "labels": {
                    "routing.task_class": "implementation",
                    "routing.interaction_required": False,
                    "routing.semantic_risk": 0,
                },
            }
            for case in view["cases"]
        ]
    }


def test_inspect_module_v2_validates_and_uses_cohort_latest_policy():
    result = validate_abc_adjudication_module(MODULE)
    assert result["valid"] is True
    assert result["schema"] == ABC_ADJUDICATION_MODULE_SCHEMA_V2
    assert result["runtime_kind"] == "inspect-ai"
    value = json.loads(MODULE.read_text(encoding="utf-8"))
    assert value["runtime"]["agent"]["version_policy"] == "latest-at-cohort-start"
    assert value["runtime"]["network"]["sandbox_network"] == "none"
    assert value["runtime"]["network"]["provider_credentials_location"] == "host-only"
    assert value["credentials"]["secrets_in_sandbox"] is False


def test_version_key_orders_moving_codex_releases():
    assert inspect_runtime._version_key("0.156.1") == (0, 156, 1)
    assert inspect_runtime._version_key("0.157.0") > inspect_runtime._version_key("0.156.9")
    assert inspect_runtime._version_key("latest") == ()


def test_json_completion_accepts_plain_and_fenced_json():
    expected = {"records": []}
    assert inspect_runtime._json_completion('{"records": []}') == expected
    assert (
        inspect_runtime._json_completion(
            '~~~'.replace("~", "`") + 'json\n{"records": []}\n' + '~~~'.replace("~", "`")
        )
        == expected
    )


def test_sample_retry_count_uses_evalsample_error_retries_contract():
    class Sample:
        error_retries = [object(), object()]

    class CleanSample:
        error_retries = None

    assert inspect_runtime._sample_retry_count(Sample()) == 2
    assert inspect_runtime._sample_retry_count(CleanSample()) == 0


def test_wrap_pass_preserves_existing_adjudication_contract(tmp_path: Path):
    view_path = _authoring_view(tmp_path)
    output = _valid_output(view_path)

    contract = inspect_runtime._wrap_pass(
        view_path,
        output,
        adjudicator_id="codex-a",
        study="routing-semantic-v1",
    )

    assert contract["schema"] == (
        "agent-workflow-benchmark/decision-study-adjudication-pass/v1"
    )
    assert contract["adjudicator_id"] == "codex-a"
    assert contract["input_view_sha256"] == inspect_runtime.sha256_file(view_path)
    assert len(contract["records"]) == 120
    assert sum(len(item["labels"]) for item in contract["records"]) == 360
    assert contract["attestation"] == {
        "independent": True,
        "treatment_outputs_seen": False,
        "other_adjudicator_labels_seen": False,
    }


def test_wrap_pass_rejects_missing_case(tmp_path: Path):
    view_path = _authoring_view(tmp_path)
    output = _valid_output(view_path)
    output["records"].pop()

    with pytest.raises(WorkflowError, match="case set mismatch"):
        inspect_runtime._wrap_pass(
            view_path,
            output,
            adjudicator_id="codex-a",
            study="routing-semantic-v1",
        )


def test_runtime_lock_records_resolved_latest_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        inspect_runtime,
        "_require_inspect_dependencies",
        lambda: (object(), object()),
    )
    monkeypatch.setattr(
        inspect_runtime,
        "resolve_latest_codex_cli",
        lambda: {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.999.7",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex-0.999.7",
        },
    )
    monkeypatch.setattr(
        inspect_runtime,
        "_docker_identity",
        lambda: {
            "docker": "Docker version 99.0.0",
            "compose": "Docker Compose version v99.0.0",
        },
    )

    path = tmp_path / "runtime-lock.json"
    result = inspect_runtime.create_inspect_runtime_lock(MODULE, path)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert result["codex_cli"]["requested"] == "latest"
    assert result["codex_cli"]["resolved"] == "0.999.7"
    assert stored["frozen_for_cohort"] is True
    assert stored["backend"] == "inspect-ai"
    assert len(result["sha256"]) == 64

    loaded = inspect_runtime._load_runtime_lock(
        path,
        validate_abc_adjudication_module(MODULE),
    )
    assert loaded["codex_cli"]["resolved"] == "0.999.7"


def test_runtime_lock_rejects_other_module(tmp_path: Path):
    module = validate_abc_adjudication_module(MODULE)
    lock = {
        "schema": inspect_runtime.RUNTIME_LOCK_SCHEMA,
        "created_at": "2026-09-25T00:00:00+00:00",
        "module_id": "wrong-module",
        "module_version": "2.0.0",
        "module_sha256": module["module_sha256"],
        "backend": "inspect-ai",
        "inspect_ai_version": inspect_runtime.INSPECT_AI_VERSION,
        "inspect_swe_version": inspect_runtime.INSPECT_SWE_VERSION,
        "codex_cli": {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.999.7",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex",
        },
        "docker": {
            "docker": "Docker version 99",
            "compose": "Docker Compose version 99",
        },
        "frozen_for_cohort": True,
    }
    path = tmp_path / "bad-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(WorkflowError, match="module_id"):
        inspect_runtime._load_runtime_lock(path, module)


def test_static_qualification_is_not_ready_until_live_gates_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        inspect_runtime,
        "_require_inspect_dependencies",
        lambda: (object(), object()),
    )
    monkeypatch.setattr(
        inspect_runtime,
        "_docker_identity",
        lambda: {
            "docker": "Docker version 99.0.0",
            "compose": "Docker Compose version v99.0.0",
        },
    )
    module = validate_abc_adjudication_module(MODULE)
    runtime_lock = tmp_path / "runtime-lock.json"
    lock = {
        "schema": inspect_runtime.RUNTIME_LOCK_SCHEMA,
        "created_at": "2026-09-25T00:00:00+00:00",
        "module_id": module["module_id"],
        "module_version": module["module_version"],
        "module_sha256": module["module_sha256"],
        "backend": "inspect-ai",
        "inspect_ai_version": inspect_runtime.INSPECT_AI_VERSION,
        "inspect_swe_version": inspect_runtime.INSPECT_SWE_VERSION,
        "codex_cli": {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.999.7",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex",
        },
        "docker": {
            "docker": "Docker version 99",
            "compose": "Docker Compose version 99",
        },
        "frozen_for_cohort": True,
    }
    runtime_lock.write_text(json.dumps(lock), encoding="utf-8")

    destination = tmp_path / "qualification.json"
    result = inspect_runtime.inspect_static_qualification(
        MODULE,
        destination,
        runtime_lock_path=runtime_lock,
    )

    assert result["qualified"] is False
    assert result["gates"]["IA-1"]["status"] == "pass"
    assert result["gates"]["IA-2"]["status"] == "pending"
    assert result["gates"]["IA-3"]["status"] == "partial"


def test_synthetic_qualification_view_never_uses_real_case_ids(tmp_path: Path):
    path = tmp_path / "synthetic.json"
    value = inspect_runtime._synthetic_qualification_view(path)
    ids = {item["case_id"] for item in value["cases"]}
    assert ids == {"inspect-qualification-001", "inspect-qualification-002"}
    assert not any(item.startswith("rsv1-") for item in ids)


def test_direct_wrapper_container_user_matches_host_uid_gid(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(inspect_runtime.os, "getuid", lambda: 1234)
    monkeypatch.setattr(inspect_runtime.os, "getgid", lambda: 5678)

    assert inspect_runtime._direct_wrapper_container_user() == "1234:5678"


def test_direct_and_inspect_modules_share_prompt_and_frozen_identities():
    direct = json.loads(
        (
            ROOT
            / "modules"
            / "abc-adjudication"
            / "routing-semantic-v1.module.json"
        ).read_text(encoding="utf-8")
    )
    inspect = json.loads(MODULE.read_text(encoding="utf-8"))

    assert direct["prompt"]["template"] == inspect["prompt"]["template"]
    direct_files = {item["id"]: item for item in direct["required_files"]}
    inspect_files = {item["id"]: item for item in inspect["required_files"]}
    for item_id in ("oracle-view", "routing-corpus"):
        assert direct_files[item_id]["sha256"] == inspect_files[item_id]["sha256"]


def test_passing_qualification_is_required_for_real_runs(tmp_path: Path):
    module = validate_abc_adjudication_module(MODULE)
    runtime_lock = tmp_path / "runtime-lock.json"
    lock = {
        "schema": inspect_runtime.RUNTIME_LOCK_SCHEMA,
        "created_at": "2026-09-25T00:00:00+00:00",
        "module_id": module["module_id"],
        "module_version": module["module_version"],
        "module_sha256": module["module_sha256"],
        "backend": "inspect-ai",
        "inspect_ai_version": inspect_runtime.INSPECT_AI_VERSION,
        "inspect_swe_version": inspect_runtime.INSPECT_SWE_VERSION,
        "codex_cli": {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.999.7",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex",
        },
        "docker": {
            "docker": "Docker version 99",
            "compose": "Docker Compose version 99",
        },
        "frozen_for_cohort": True,
    }
    runtime_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(WorkflowError, match="requires a passing P0A qualification"):
        inspect_runtime._require_passing_qualification(
            None,
            module=module,
            runtime_lock_path=runtime_lock,
            allow_unqualified=False,
        )

    gates = {
        gate: {"status": "pass"}
        for gate in ("IA-1", "IA-2", "IA-3", "IA-4", "IA-5", "IA-6", "IA-7", "IA-8")
    }
    qualification = tmp_path / "qualification.json"
    value = {
        "schema": inspect_runtime.INSPECT_QUALIFICATION_SCHEMA,
        "created_at": "2026-09-25T00:00:00+00:00",
        "module_id": module["module_id"],
        "module_sha256": module["module_sha256"],
        "runtime_lock_sha256": inspect_runtime.sha256_file(runtime_lock),
        "qualified": True,
        "gates": gates,
    }
    qualification.write_text(json.dumps(value), encoding="utf-8")

    inspect_runtime._require_passing_qualification(
        qualification,
        module=module,
        runtime_lock_path=runtime_lock,
        allow_unqualified=False,
    )

    value["gates"]["IA-7"]["status"] = "pending"
    value["qualified"] = False
    qualification.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkflowError, match="not passing"):
        inspect_runtime._require_passing_qualification(
            qualification,
            module=module,
            runtime_lock_path=runtime_lock,
            allow_unqualified=False,
        )


def test_resolve_codex_npm_latest_uses_exact_registry_version(
    monkeypatch: pytest.MonkeyPatch,
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"version":"0.321.4"}'

    monkeypatch.setattr(
        inspect_runtime.urllib.request,
        "urlopen",
        lambda request, timeout=30: Response(),
    )
    assert inspect_runtime._resolve_codex_npm_latest() == "0.321.4"


def test_resolve_codex_npm_latest_rejects_nonversion(
    monkeypatch: pytest.MonkeyPatch,
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"version":"latest"}'

    monkeypatch.setattr(
        inspect_runtime.urllib.request,
        "urlopen",
        lambda request, timeout=30: Response(),
    )
    with pytest.raises(WorkflowError, match="invalid Codex CLI version"):
        inspect_runtime._resolve_codex_npm_latest()
