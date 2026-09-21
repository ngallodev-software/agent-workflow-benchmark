from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema_contracts import read_contract, validate_instance
from agent_workflow.errors import WorkflowError
from .auth import validate_authentication_config
from .common import canonical_json_sha256, child, safe_relative
from .runtime import validate_runtime_lock

BENCHMARK_SPEC_SCHEMA = "agent-workflow/benchmark-spec/v1"
BENCHMARK_SPEC_V3_SCHEMA = "agent-workflow/benchmark-spec/v3"
BENCHMARK_SPEC_SCHEMAS = {BENCHMARK_SPEC_SCHEMA, "agent-workflow/benchmark-spec/v2", BENCHMARK_SPEC_V3_SCHEMA}
BENCHMARK_SCORING_CONTRACT_SCHEMA = "agent-workflow/benchmark-scoring-contract/v1"
BENCHMARK_EXECUTOR_SCHEMA = "agent-workflow/benchmark-executor-config/v1"
BENCHMARK_RUN_SCHEMA = "agent-workflow/benchmark-run/v1"
BENCHMARK_RUN_V2_SCHEMA = "agent-workflow/benchmark-run/v2"
BENCHMARK_ARM_SCHEMA = "agent-workflow/benchmark-arm/v1"
BENCHMARK_PAIR_SCHEMA = "agent-workflow/benchmark-pair/v1"
BENCHMARK_PHASE_EVENT_SCHEMA = "agent-workflow/benchmark-phase-event/v1"
BENCHMARK_MACHINE_SCORE_SCHEMA = "agent-workflow/benchmark-machine-score/v1"
BENCHMARK_MACHINE_SCORE_V2_SCHEMA = "agent-workflow/benchmark-machine-score/v2"
BENCHMARK_REVIEW_ASSIGNMENT_SCHEMA = "agent-workflow/benchmark-review-assignment/v1"
BENCHMARK_HUMAN_REVIEW_SCHEMA = "agent-workflow/benchmark-human-review/v1"
BENCHMARK_CONSOLIDATION_SCHEMA = "agent-workflow/benchmark-consolidation-receipt/v1"
BENCHMARK_REPORT_SCHEMA = "agent-workflow/benchmark-report/v2"
BENCHMARK_VISUAL_EVIDENCE_SCHEMA = "agent-workflow/benchmark-visual-evidence/v1"
BENCHMARK_OPERATING_POLICY_SCHEMA = "agent-workflow/benchmark-operating-policy/v1"


LEGACY_INTERNAL_ARMS = ("control_raw", "workflow_full")


def normalized_arm_profiles(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the two benchmark treatments keyed by the stable internal arm slots.

    Historical v1/v2 artifacts keep their original control_raw/workflow_full
    semantics.  v3 separates statistical role (control/candidate) from treatment
    identity while retaining the internal slots required by existing arm/pair
    evidence schemas.
    """
    if spec.get("schema") == BENCHMARK_SPEC_V3_SCHEMA:
        source_roles = {"control_raw": "control", "workflow_full": "candidate"}
        return {
            internal: {**spec["arms"][source], "_source_role": source}
            for internal, source in source_roles.items()
        }
    return {
        "control_raw": {
            **spec["arms"]["control_raw"],
            "_source_role": "control_raw",
            "treatment_id": "raw-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
        "workflow_full": {
            **spec["arms"]["workflow_full"],
            "_source_role": "workflow_full",
            "treatment_id": "structured-direct/v1",
            "runner": {"kind": "direct-executor", "agent_class": None},
        },
    }


def run_schema_for_spec(spec: dict[str, Any]) -> str:
    return BENCHMARK_RUN_V2_SCHEMA if spec.get("schema") == BENCHMARK_SPEC_V3_SCHEMA else BENCHMARK_RUN_SCHEMA


def _unique(items: list[str], label: str) -> None:
    if len(items) != len(set(items)):
        raise WorkflowError(f"benchmark specification contains duplicate {label}")


def _require_file(root: Path, relative: str, label: str) -> Path:
    path = child(root, safe_relative(relative, label), label)
    if not path.is_file():
        raise WorkflowError(f"{label} not found: {path}")
    return path


def _require_directory(root: Path, relative: str, label: str) -> Path:
    path = child(root, safe_relative(relative, label), label)
    if not path.is_dir():
        raise WorkflowError(f"{label} not found: {path}")
    return path


def load_scoring_contract(path: Path, spec: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Load and validate the explicit corrected-version scoring authority."""
    path = path.expanduser().resolve()
    spec = spec or read_contract(path)
    relative = spec.get("scoring_contract_path")
    if not isinstance(relative, str):
        return None
    contract_path = _require_file(path.parent, relative, "scoring contract")
    contract = read_contract(contract_path, BENCHMARK_SCORING_CONTRACT_SCHEMA)
    if contract["benchmark_id"] != spec["benchmark_id"] or contract["benchmark_version"] != spec["version"]:
        raise WorkflowError("scoring contract benchmark identity does not match benchmark specification")
    dimension_ids = [str(item["id"]) for item in contract["dimensions"]]
    _unique(dimension_ids, "scoring-contract dimension IDs")
    check_ids: list[str] = []
    total = 0.0
    for dimension in contract["dimensions"]:
        ids = [str(item["id"]) for item in dimension["checks"]]
        _unique(ids, f"scoring-contract check IDs in {dimension['id']}")
        check_ids.extend(ids)
        observed = sum(float(item["max_points"]) for item in dimension["checks"] )
        maximum = float(dimension["max_points"])
        if abs(observed - maximum) > 1e-9:
            raise WorkflowError(
                f"scoring contract dimension {dimension['id']} points must total {maximum:g}, observed {observed:g}"
            )
        total += maximum
    _unique(check_ids, "scoring-contract check IDs")
    if abs(total - float(contract["total_points"])) > 1e-9 or abs(total - 100.0) > 1e-9:
        raise WorkflowError(f"scoring contract points must total 100, observed {total:g}")
    evaluator = _require_file(path.parent, str(contract["evaluator_path"]), "scoring evaluator")
    if not evaluator.is_file():  # pragma: no cover - _require_file owns the error
        raise WorkflowError(f"scoring evaluator not found: {evaluator}")
    return contract


def validate_spec(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    value = read_contract(path)
    if value.get("schema") not in BENCHMARK_SPEC_SCHEMAS:
        raise WorkflowError(f"unexpected benchmark specification schema: {value.get('schema')}")
    root = path.parent
    _require_file(root, value["canonical_task"], "canonical task")
    _require_directory(root, value["fixture"]["template_path"], "fixture template")
    _require_file(root, value["visual"]["rubric_path"], "visual rubric")
    runtime_lock_path = _require_file(root, value["visual"]["runtime_lock_path"], "visual runtime lock")
    from .common import read_object
    validate_runtime_lock(read_object(runtime_lock_path), claim_level=str(value["claim_level"]))
    phase_ids = [str(item["id"]) for item in value["phases"]]
    _unique(phase_ids, "phase IDs")
    for phase in value["phases"]:
        _require_file(root, str(phase["prompt_path"]), f"phase {phase['id']} prompt")
    arms = value["arms"]
    if value.get("schema") == BENCHMARK_SPEC_V3_SCHEMA:
        if set(arms) != {"control", "candidate"}:
            raise WorkflowError("benchmark v3 requires exactly control and candidate roles")
        treatment_ids = [str(profile["treatment_id"]) for profile in arms.values()]
        _unique(treatment_ids, "treatment IDs")
        for role, profile in arms.items():
            runner = profile["runner"]
            if runner["kind"] == "agent-workflow" and not runner.get("agent_class"):
                raise WorkflowError(f"{role} agent-workflow runner requires agent_class")
    else:
        if set(arms) != {"control_raw", "workflow_full"}:
            raise WorkflowError(
                "initial benchmark requires exactly control_raw and workflow_full arms"
            )
    for arm, profile in arms.items():
        _require_file(root, str(profile["wrapper_path"]), f"{arm} wrapper")
        if value.get("schema") != BENCHMARK_SPEC_V3_SCHEMA and profile["profile_id"] not in {"control-raw/v1", "workflow-full/v1"}:
            raise WorkflowError(f"unsupported initial constraint profile: {profile['profile_id']}")
    scheduling = value["scheduling"]
    if int(scheduling["pair_concurrency"]) != 1:
        raise WorkflowError("initial benchmark supports one pair at a time; each pair still runs both arms concurrently")
    retries = int(scheduling["infrastructure_retries"])
    if retries < 0 or retries > 3:
        raise WorkflowError("benchmark infrastructure retries must be between 0 and 3")
    cases = value["cases"]
    _unique([str(item["id"]) for item in cases], "case IDs")
    for case in cases:
        _require_file(root, str(case["input_path"]), f"case {case['id']} input")
        scope = case["allowed_scope"]
        for key in ("writable_paths", "writable_trees", "disposable_trees"):
            for relative in scope.get(key, []):
                safe_relative(str(relative), f"case {case['id']} {key}")
    scorers = value["machine_scoring"]["scorers"]
    _unique([str(item["id"]) for item in scorers], "scorer IDs")
    total = sum(float(item["max_points"]) for item in scorers)
    if abs(total - 100.0) > 1e-9:
        raise WorkflowError(f"machine scorer points must total 100, observed {total:g}")
    if abs(float(value["composite"]["machine_weight"]) + float(value["composite"]["human_weight"]) - 1.0) > 1e-9:
        raise WorkflowError("benchmark composite weights must total 1.0")
    required_dimensions = {
        "hidden_functional",
        "public_regression",
        "robustness",
        "accessibility_ui",
        "scope_completeness",
        "engineering_quality",
    }
    scorer_dimensions = {str(item["dimension"]) for item in scorers}
    if scorer_dimensions != required_dimensions:
        raise WorkflowError("benchmark machine scoring must define the six frozen dimensions")
    contract = load_scoring_contract(path, value)
    if contract is not None:
        contract_dimensions = {str(item["id"]): float(item["max_points"]) for item in contract["dimensions"]}
        scorer_points = {str(item["dimension"]): float(item["max_points"]) for item in scorers}
        if contract_dimensions != scorer_points:
            raise WorkflowError("benchmark scorer dimensions/points do not match the scoring contract")
    return value


def validate_executor_config(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    value = read_contract(path, BENCHMARK_EXECUTOR_SCHEMA)
    validate_authentication_config(value)
    template = value["argv_template"]
    placeholders = "\n".join(str(item) for item in template)
    delivery = value["prompt_delivery"]["source"]
    if delivery == "argv" and "{prompt_file}" not in placeholders:
        raise WorkflowError("argv prompt delivery requires {prompt_file}")
    billing = value["billing"]
    auth_mode = value["authentication"]["mode"]
    if auth_mode == "subscription-session":
        if billing["mode"] != "subscription":
            raise WorkflowError("subscription authentication requires subscription billing semantics")
        if billing["provider_billed_cost_semantics"] != "not-attributable":
            raise WorkflowError("subscription billing must use not-attributable provider cost semantics")
    elif auth_mode == "synthetic-none" and billing["mode"] != "synthetic":
        raise WorkflowError("synthetic authentication requires synthetic billing semantics")
    return value


def validate_value(value: dict[str, Any], schema: str, artifact: str) -> dict[str, Any]:
    validate_instance(value, schema, artifact=artifact)
    return value


def contract_sha256(value: dict[str, Any]) -> str:
    return canonical_json_sha256(value)
