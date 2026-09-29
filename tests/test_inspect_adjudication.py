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
V2_MODULE = (
    ROOT
    / "modules"
    / "abc-adjudication"
    / "routing-semantic-v2.inspect.module.json"
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


def test_validated_module_study_id_uses_flat_validator_summary():
    validated = validate_abc_adjudication_module(V2_MODULE)

    assert validated["study_id"] == "routing-semantic-v2"
    assert "task" not in validated
    assert inspect_runtime._validated_module_study_id(validated) == "routing-semantic-v2"


def test_validated_module_study_id_fails_closed_when_identity_missing():
    with pytest.raises(WorkflowError, match="unsupported Inspect qualification study: empty"):
        inspect_runtime._validated_module_study_id({})


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
        lambda **_: (object(), object()),
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


def test_v2_runtime_lock_records_structured_output_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module_path = V2_MODULE
    capability = {
        "capability": inspect_runtime.INSPECT_SWE_OUTPUT_SCHEMA_CAPABILITY,
        "enabled": True,
        "inspect_swe_version": inspect_runtime.INSPECT_SWE_VERSION,
        "source_path": "/tmp/codex_cli.py",
        "source_sha256": "a" * 64,
        "upstream_git_blob_sha1": "b" * 40,
    }
    monkeypatch.setattr(
        inspect_runtime,
        "_require_inspect_dependencies",
        lambda **_: (object(), object()),
    )
    monkeypatch.setattr(
        inspect_runtime,
        "assert_inspect_swe_output_schema_capability",
        lambda: capability,
    )
    monkeypatch.setattr(
        inspect_runtime,
        "resolve_latest_codex_cli",
        lambda: {
            "policy": "latest-at-cohort-start",
            "requested": "latest",
            "resolved": "0.158.0",
            "platform": "linux-x64",
            "cached_path": "/tmp/codex-0.158.0",
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

    path = tmp_path / "v2-runtime-lock.json"
    inspect_runtime.create_inspect_runtime_lock(module_path, path)
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert stored["structured_output"] == {
        "mode": "codex-output-schema",
        "capability": inspect_runtime.INSPECT_SWE_OUTPUT_SCHEMA_CAPABILITY,
        "inspect_swe_source_sha256": "a" * 64,
        "upstream_git_blob_sha1": "b" * 40,
    }

    loaded = inspect_runtime._load_runtime_lock(
        path,
        validate_abc_adjudication_module(module_path),
    )
    assert loaded["structured_output"]["mode"] == "codex-output-schema"


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
        lambda **_: (object(), object()),
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
    model = "openai-api/codex-lb/deepseek-flash"
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
            model=model,
            allow_unqualified=False,
        )

    gates = {
        gate: {"status": "pass"}
        for gate in ("IA-1", "IA-2", "IA-3", "IA-4", "IA-5", "IA-6", "IA-7", "IA-8")
    }
    gates["IA-2"]["evidence"] = {"model": model}
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
        model=model,
        allow_unqualified=False,
    )

    with pytest.raises(WorkflowError, match="qualification model does not match"):
        inspect_runtime._require_passing_qualification(
            qualification,
            module=module,
            runtime_lock_path=runtime_lock,
            model="openai-api/codex-lb/gpt-6-luna",
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
            model=model,
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


class _FakeUsage:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, mode="json"):
        return dict(self.values)


class _FakeOutput:
    def __init__(self):
        self.usage = _FakeUsage(
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
        )


class _FakeSample:
    def __init__(self):
        self.output = _FakeOutput()
        self.model_usage = {
            "openai-api/test": _FakeUsage(
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
            )
        }
        self.events = [
            type("Event", (), {"event": "model", "retries": None, "cache": None})(),
            type("Event", (), {"event": "tool", "retries": None, "cache": None})(),
            type("Event", (), {"event": "model", "retries": 1, "cache": None})(),
            type("Event", (), {"event": "model", "retries": None, "cache": "read"})(),
        ]
        self.messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "reasoning",
                        "reasoning": "redacted",
                        "summary": "bounded summary",
                    }
                ],
            }
        ]


def test_v2_provenance_separates_final_output_and_aggregate_session_usage():
    sample = _FakeSample()
    value = inspect_runtime._sample_usage_provenance(sample)
    assert value["final_output_usage"]["input_tokens"] == 10
    assert value["aggregate_session_usage"]["openai-api/test"]["input_tokens"] == 100
    assert value["model_call_count"] == 3
    assert value["provider_request_count"] == 3


def test_v2_model_and_provider_counts_distinguish_retries_and_cache_reads():
    sample = _FakeSample()

    model_calls, provider_requests = inspect_runtime._sample_model_request_counts(sample)

    assert model_calls == 3
    assert provider_requests == 3


def test_v2_provider_request_count_fails_closed_on_invalid_retry_evidence():
    sample = _FakeSample()
    sample.events = [
        type("Event", (), {"event": "model", "retries": "unknown", "cache": None})()
    ]

    model_calls, provider_requests = inspect_runtime._sample_model_request_counts(sample)

    assert model_calls == 1
    assert provider_requests is None


def test_v1_provenance_shape_remains_historical_while_v2_is_scoped():
    sample = _FakeSample()

    v1 = inspect_runtime._sample_provenance_fields(
        sample, study="routing-semantic-v1"
    )
    assert set(v1) == {"model_usage"}
    assert v1["model_usage"]["input_tokens"] == 10

    v2 = inspect_runtime._sample_provenance_fields(
        sample, study="routing-semantic-v2"
    )
    assert "model_usage" not in v2
    assert v2["final_output_usage"]["input_tokens"] == 10
    assert v2["aggregate_session_usage"]["openai-api/test"]["input_tokens"] == 100
    assert v2["reasoning_summary"]["observed"] is True


def test_reasoning_summary_capture_is_observational_not_raw_reasoning():
    value = inspect_runtime._reasoning_summary_stats(_FakeSample())
    assert value == {
        "observed": True,
        "items": 1,
        "characters": len("bounded summary"),
    }


def test_v2_evidence_preflight_schema_requires_ia9_through_ia11():
    schema = {
        "schema": "agent-workflow-benchmark/routing-semantic-v2-evidence-preflight/v1",
        "created_at": "2026-09-27T00:00:00+00:00",
        "study_id": "routing-semantic-v2",
        "protocol_version": "routing-semantic-oracle-v2.0.0",
        "codex_version": "1.2.3",
        "model": "openai-api/codex-lb/deepseek-flash",
        "model_args": {"responses_api": True},
        "passed": True,
        "gates": {
            "IA-9": {"status": "pass"},
            "IA-10": {"status": "pass"},
            "IA-11": {"status": "pass"},
        },
        "completion_sources": {
            "A": "model_output.completion",
            "B": "model_output.completion",
            "C": "messages.terminal_assistant",
        },
        "artifacts": {"view": "/private/view.json"},
        "real_cohort_ready": False,
        "blocking_reason": "real cohort identities are not frozen",
    }
    inspect_runtime.validate_instance(
        schema,
        "agent-workflow-benchmark/routing-semantic-v2-evidence-preflight/v1",
        artifact="test",
    )


def test_v2_model_output_schema_groups_identical_eligibility_shapes(tmp_path: Path):
    view_path = tmp_path / "view.json"
    inspect_runtime._synthetic_v2_evidence_view(view_path)

    schema = inspect_runtime._v2_model_output_schema(view_path)

    assert inspect_runtime.V2_OUTPUT_SCHEMA_STRATEGY == (
        "eligibility-grouped-case-enum/v1"
    )
    assert schema["type"] == "object"
    records = schema["properties"]["records"]
    assert "minItems" not in records
    assert "maxItems" not in records
    variants = records["items"]["anyOf"]
    assert len(variants) == 1

    item = variants[0]
    case_schema = item["properties"]["case_id"]
    assert case_schema["type"] == "string"
    assert tuple(case_schema["enum"]) == (
        "rsv2-preflight-001",
        "rsv2-preflight-002",
    )
    assert item["required"] == ["case_id", "labels", "justifications"]
    labels = item["properties"]["labels"]
    justifications = item["properties"]["justifications"]
    assert set(labels["required"]) == {
        "routing.task_class",
        "routing.interaction_required",
        "routing.semantic_risk",
    }
    assert justifications["required"] == labels["required"]
    evidence = justifications["properties"]["routing.task_class"]["properties"][
        "decisive_case_evidence"
    ]
    assert "minItems" not in evidence
    assert "maxItems" not in evidence
    assert evidence["items"]["maxLength"] == 320

    serialized = json.dumps(schema, sort_keys=True)
    assert '"const"' not in serialized
    assert '"minItems"' not in serialized
    assert '"maxItems"' not in serialized


def test_v2_real_schema_collapses_120_identical_case_shapes(tmp_path: Path):
    view = comparative.oracle_authoring_view(
        comparative.load_study_corpus("routing-semantic-v2")
    )
    view_path = tmp_path / "routing-semantic-v2-view.json"
    view_path.write_text(
        json.dumps(view, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    schema = inspect_runtime._v2_model_output_schema(view_path)
    variants = schema["properties"]["records"]["items"]["anyOf"]

    assert len(view["cases"]) == 120
    assert len(variants) == 1
    assert len(variants[0]["properties"]["case_id"]["enum"]) == 120
    assert len(json.dumps(schema, sort_keys=True)) < 10_000


def test_v2_post_generation_justification_cardinality_remains_fail_closed():
    valid = {
        "decisive_case_evidence": ["case-grounded fact"],
        "rubric_rule": "frozen rule",
        "ambiguity": "none",
    }
    inspect_runtime._validate_justification(
        "routing.task_class",
        valid,
        case_id="case-1",
    )

    for evidence in ([], ["a", "b", "c", "d"]):
        invalid = {**valid, "decisive_case_evidence": evidence}
        with pytest.raises(WorkflowError, match="1-3 decisive_case_evidence"):
            inspect_runtime._validate_justification(
                "routing.task_class",
                invalid,
                case_id="case-1",
            )


def test_v2_whole_completion_parser_rejects_prose_prefixed_json():
    completion = (
        "Read both files. Now emitting adjudications.\n\n"
        '{"records":[]}'
    )
    with pytest.raises(WorkflowError, match="did not return a JSON object"):
        inspect_runtime._json_completion(completion)


def test_v2_deterministic_wrapper_fixture_preserves_justifications(tmp_path: Path):
    view_path = tmp_path / "view.json"
    inspect_runtime._synthetic_v2_evidence_view(view_path)

    output = inspect_runtime._deterministic_output_for_view(
        view_path,
        study="routing-semantic-v2",
    )

    assert output["records"]
    first = output["records"][0]
    assert set(first["justifications"]) == set(first["labels"])
    for value in first["justifications"].values():
        assert 1 <= len(value["decisive_case_evidence"]) <= 3
        assert value["rubric_rule"]
        assert value["ambiguity"] == "none"


def test_v2_preflight_prompt_is_packaged_and_matches_docker_source():
    packaged = inspect_runtime._v2_prompt_template_path()
    docker_source = ROOT / "docker" / "adjudication" / "START_PROMPT.v2.template.md"

    assert packaged.is_file()
    assert packaged.read_text(encoding="utf-8") == docker_source.read_text(
        encoding="utf-8"
    )


def test_v2_resolution_renderer_probe_is_package_local(tmp_path: Path):
    decision_id = "routing.semantic_risk"
    case_id = "synthetic-1"
    justification = {
        "decisive_case_evidence": ["The request affects production state."],
        "rubric_rule": "Production impact is high semantic consequence.",
        "ambiguity": "none",
    }
    view = {
        "study_id": "routing-semantic-v2",
        "dataset_version": "synthetic",
        "cases": [
            {
                "case_id": case_id,
                "task": "Change production state.",
                "metadata": {},
                "oracle_eligible": [decision_id],
            }
        ],
        "decision_seams": [
            {
                "decision_id": decision_id,
                "oracle_type": "ordinal",
                "levels": [0, 1, 2],
            }
        ],
    }
    contracts = []
    for label in (0, 1, 2):
        contracts.append(
            {
                "records": [
                    {
                        "case_id": case_id,
                        "labels": {decision_id: label},
                        "justifications": {decision_id: justification},
                    }
                ]
            }
        )

    result = inspect_runtime._probe_v2_resolution_renderer(
        output_root=tmp_path,
        view=view,
        a_contract=contracts[0],
        b_contract=contracts[1],
        c_contract=contracts[2],
        decision_id=decision_id,
    )

    assert result["passed"] is True
    assert Path(result["markdown"]).is_file()
    rendered = Path(result["markdown"]).read_text(encoding="utf-8")
    assert "Independent structured justifications" in rendered
    assert justification["decisive_case_evidence"][0] in rendered


def test_v2_prompt_makes_evidence_array_contract_explicit():
    prompt = inspect_runtime._v2_prompt_template_path().read_text(encoding="utf-8")
    assert "MUST be a JSON array, never a scalar string" in prompt
    assert '"decisive_case_evidence": ["concise case-grounded statement"]' in prompt


def test_v2_preflight_invalid_completion_preserves_diagnostics(tmp_path: Path):
    view_path = tmp_path / "view.json"
    inspect_runtime._synthetic_v2_evidence_view(view_path)
    role_dir = tmp_path / "a"

    with pytest.raises(WorkflowError, match="diagnostic="):
        inspect_runtime._wrap_v2_preflight_completion(
            view_path=view_path,
            completion='{"records":[]}',
            completion_source="model_output.completion",
            adjudicator_id="preflight-a",
            role_dir=role_dir,
        )

    assert (role_dir / "raw-completion.txt").read_text(encoding="utf-8") == '{"records":[]}'
    diagnostic = json.loads(
        (role_dir / "contract-validation-error.json").read_text(encoding="utf-8")
    )
    assert diagnostic["adjudicator_id"] == "preflight-a"
    assert diagnostic["completion_source"] == "model_output.completion"
    assert diagnostic["error"]


def test_v2_preflight_model_args_default_is_shell_safe():
    script = (
        ROOT / "scripts" / "adjudication" / "v2-evidence-preflight.sh"
    ).read_text(encoding="utf-8")
    assert 'MODEL_ARGS_JSON="${V2_ADJUDICATION_MODEL_ARGS_JSON:-}"' in script
    assert 'MODEL_ARGS_JSON=\'{"responses_api":true}\'' in script
    assert 'V2_ADJUDICATION_MODEL_ARGS_JSON:-{\\"responses_api\\":true}' not in script


def test_v2_adjudicator_identity_is_frozen_to_deepseek_flash():
    assert inspect_runtime._validate_v2_adjudicator_identity(
        "openai-api/codex-lb/deepseek-flash",
        {"responses_api": True},
    ) == {"responses_api": True}

    with pytest.raises(WorkflowError, match="model is frozen"):
        inspect_runtime._validate_v2_adjudicator_identity(
            "openai-api/codex-lb/gpt-6-luna",
            {"responses_api": True},
        )

    with pytest.raises(WorkflowError, match="model args are frozen"):
        inspect_runtime._validate_v2_adjudicator_identity(
            "openai-api/codex-lb/deepseek-flash",
            {"responses_api": True, "reasoning_effort": "high"},
        )


class _FakeAssistantMessage:
    role = "assistant"
    source = "generate"
    tool_calls = None

    def __init__(self, text: str):
        self.text = text


class _FakeToolCallingAssistantMessage(_FakeAssistantMessage):
    tool_calls = [object()]


class _FakeSampleWithTerminalMessage:
    def __init__(self, *, completion: str, messages: list[object]):
        self.output = type("Output", (), {"completion": completion})()
        self.messages = messages


def test_v2_adjudication_completion_falls_back_to_terminal_assistant_message():
    expected = '{"records":[]}'
    sample = _FakeSampleWithTerminalMessage(
        completion="",
        messages=[
            _FakeToolCallingAssistantMessage("not terminal"),
            _FakeAssistantMessage(expected),
        ],
    )

    text, source = inspect_runtime._sample_adjudication_completion(
        sample,
        study="routing-semantic-v2",
    )

    assert text == expected
    assert source == "messages.terminal_assistant"
    assert inspect_runtime._json_completion(text) == {"records": []}


def test_v2_adjudication_completion_prefers_nonempty_model_output():
    sample = _FakeSampleWithTerminalMessage(
        completion='{"records":[]}',
        messages=[_FakeAssistantMessage('{"records":[{"case_id":"other"}]}')],
    )

    text, source = inspect_runtime._sample_adjudication_completion(
        sample,
        study="routing-semantic-v2",
    )

    assert text == '{"records":[]}'
    assert source == "model_output.completion"


def test_v1_adjudication_completion_preserves_historical_output_only_contract():
    sample = _FakeSampleWithTerminalMessage(
        completion="",
        messages=[_FakeAssistantMessage('{"records":[]}')],
    )

    text, source = inspect_runtime._sample_adjudication_completion(
        sample,
        study="routing-semantic-v1",
    )

    assert text == ""
    assert source == "model_output.completion"


def test_v2_adjudication_completion_never_reuses_pre_tool_assistant_text():
    sample = _FakeSampleWithTerminalMessage(
        completion="",
        messages=[
            _FakeAssistantMessage('{"records":[]}'),
            _FakeToolCallingAssistantMessage("calling tool"),
        ],
    )

    text, source = inspect_runtime._sample_adjudication_completion(
        sample,
        study="routing-semantic-v2",
    )

    assert text == ""
    assert source == "model_output.completion"


def test_v2_preflight_force_recreates_generated_root(tmp_path: Path):
    root = tmp_path / "routing-semantic-v2-evidence-preflight"
    root.mkdir()
    stale = root / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    with pytest.raises(WorkflowError, match="directory already exists"):
        inspect_runtime._prepare_v2_preflight_root(root, force=False)

    inspect_runtime._prepare_v2_preflight_root(root, force=True)

    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_v2_preflight_failure_message_names_failed_gates_and_artifact(tmp_path: Path):
    destination = tmp_path / "preflight.json"
    record = {
        "gates": {
            "IA-9": {"status": "pass"},
            "IA-10": {"status": "fail"},
            "IA-11": {"status": "pass"},
        }
    }

    message = inspect_runtime._v2_preflight_failure_message(record, destination)

    assert "IA-10" in message
    assert "IA-9" not in message
    assert str(destination) in message
