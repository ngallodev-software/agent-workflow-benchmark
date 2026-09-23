from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import atomic_write_json, sha256_file, utc_now
from .common import format_argv, read_object, tree_sha256
from .contracts import (
    BENCHMARK_MACHINE_SCORE_SCHEMA,
    BENCHMARK_MACHINE_SCORE_V2_SCHEMA,
    BENCHMARK_SUPPLEMENTARY_SCORE_SCHEMA,
    load_scoring_contract,
    load_supplementary_scoring_contract,
    validate_spec,
    validate_value,
)
from .events import append_event
from .pairing import selected_arms
from .product_scoring import score_end_to_end_product
from .execution_seal import require_execution_seal


def _guardrail(id_: str, state: str, detail: str, *, required: bool) -> dict[str, Any]:
    return {"id": id_, "state": state, "required": required, "detail": detail}


def _core_guardrails(
    plan: Mapping[str, Any],
    pair: Mapping[str, Any],
    pair_state: Mapping[str, Any],
    arm_value: Mapping[str, Any],
    capture: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    required = set(str(item) for item in spec["eligibility"]["required_guardrails"])
    values: list[dict[str, Any]] = []
    values.append(
        _guardrail(
            "paired_identity",
            "pass" if arm_value["task_prompt_sha256"] == pair["task_prompt_sha256"] else "fail",
            "canonical task, fixture, base revision, and environment are pair-bound",
            required="paired_identity" in required,
        )
    )
    other_arm = "workflow_full" if arm_value["arm"] == "control_raw" else "control_raw"
    treatments = plan.get("treatments")
    if isinstance(treatments, Mapping):
        current_treatment = treatments.get(str(arm_value["arm"]), {})
        other_treatment = treatments.get(other_arm, {})
        treatment_ok = (
            isinstance(current_treatment, Mapping)
            and isinstance(other_treatment, Mapping)
            and current_treatment.get("treatment_id") != other_treatment.get("treatment_id")
        )
        treatment_detail = (
            f"treatment={current_treatment.get('treatment_id')}; "
            f"other={other_treatment.get('treatment_id')}; "
            f"runner={current_treatment.get('runner_kind')}"
        )
    else:
        wrapper_other = pair["arms"][other_arm]["arm_wrapper_sha256"]
        treatment_ok = arm_value["arm_wrapper_sha256"] != wrapper_other
        treatment_detail = "arm wrappers must differ while canonical task digest remains equal"
    values.append(
        _guardrail(
            "declared_treatment",
            "pass" if treatment_ok else "fail",
            treatment_detail,
            required="declared_treatment" in required,
        )
    )
    skew = float(pair_state["pair_start_skew_seconds"])
    limit = float(plan["policies"]["max_start_skew_seconds"])
    values.append(
        _guardrail(
            "start_skew",
            "pass" if skew <= limit else "fail",
            f"observed {skew:.6f}s; limit {limit:.6f}s",
            required="start_skew" in required,
        )
    )
    violations = list(arm_value.get("scope_violations", []))
    values.append(
        _guardrail(
            "writable_scope",
            "pass" if not violations else "fail",
            "no out-of-scope writes" if not violations else f"out-of-scope paths: {violations}",
            required="writable_scope" in required,
        )
    )
    sandbox = plan["executor"]["sandbox"]
    isolation_state = "pass" if sandbox.get("verified_isolation") else "not_verified"
    values.append(
        _guardrail(
            "sandbox_isolation",
            isolation_state,
            f"adapter={sandbox.get('adapter')}; verified={bool(sandbox.get('verified_isolation'))}",
            required="sandbox_isolation" in required,
        )
    )
    expected_assistance = "none" if plan["policies"].get("human_assistance") == "unassisted" else "declared"
    values.append(
        _guardrail(
            "assistance_cohort",
            "pass" if arm_value.get("assistance") == expected_assistance else "fail",
            f"cohort={plan['policies'].get('human_assistance')}; assistance={arm_value.get('assistance')}",
            required="assistance_cohort" in required,
        )
    )
    visual_state = capture.get("state") if isinstance(capture, Mapping) else None
    runtime_state = capture.get("runtime_state") if isinstance(capture, Mapping) else None
    visual_ok = visual_state == "complete" and runtime_state in {"development-verified", "publication-verified"}
    if plan["claim_level"] == "publication":
        visual_ok = visual_ok and runtime_state == "publication-verified"
    values.append(
        _guardrail(
            "visual_capture",
            "pass" if visual_ok else "fail",
            f"visual capture state={visual_state or 'missing'}; runtime_state={runtime_state or 'missing'}",
            required="visual_capture" in required,
        )
    )
    usage = arm_value.get("usage", {})
    usage_state = "pass" if usage.get("complete") is True else "not_verified"
    values.append(
        _guardrail(
            "provider_usage",
            usage_state,
            f"usage complete={usage.get('complete') is True}",
            required="provider_usage" in required,
        )
    )
    task_state = arm_value.get("state")
    values.append(
        _guardrail(
            "harness_integrity",
            "fail" if task_state == "infrastructure_failed" else "pass",
            f"arm terminal state={task_state}",
            required="harness_integrity" in required,
        )
    )
    return values


def _contract_dimension(contract: Mapping[str, Any], dimension: str) -> Mapping[str, Any]:
    for item in contract["dimensions"]:
        if item["id"] == dimension:
            return item
    raise WorkflowError(f"scoring contract has no dimension {dimension}")


def _contract_checks(
    scorer: Mapping[str, Any],
    result: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    dimension = _contract_dimension(contract, str(scorer["dimension"]))
    expected = {str(item["id"]): item for item in dimension["checks"]}
    raw = result.get("checks")
    if not isinstance(raw, list):
        raise WorkflowError(f"scorer {scorer['id']} did not provide a checks array")
    observed: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise WorkflowError(f"scorer {scorer['id']} returned a malformed check")
        check_id = str(item["id"])
        if check_id in observed:
            raise WorkflowError(f"scorer {scorer['id']} returned duplicate check {check_id}")
        if check_id not in expected:
            raise WorkflowError(f"scorer {scorer['id']} returned unknown check {check_id}")
        observed[check_id] = item
    missing = sorted(set(expected) - set(observed))
    if missing:
        raise WorkflowError(f"scorer {scorer['id']} omitted checks: {', '.join(missing)}")
    checks: list[dict[str, Any]] = []
    earned_total = 0.0
    for check_id, definition in expected.items():
        item = observed[check_id]
        passed = item.get("passed")
        if not isinstance(passed, bool):
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} did not provide boolean passed")
        maximum = float(definition["max_points"])
        partial = str(definition["partial_credit"])
        raw_earned = item.get("earned_points", maximum if passed else 0.0)
        if isinstance(raw_earned, bool) or not isinstance(raw_earned, (int, float)):
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} did not provide numeric earned_points")
        earned = float(raw_earned)
        if earned < 0 or earned > maximum:
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} points {earned:g} exceed 0..{maximum:g}")
        if partial == "none" and earned not in {0.0, maximum}:
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} does not permit partial credit")
        if passed != (earned == maximum):
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} passed state disagrees with earned points")
        evidence = item.get("evidence_reference")
        if not isinstance(evidence, str) or not evidence:
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} has no evidence reference")
        if evidence != definition["evidence_reference"]:
            raise WorkflowError(f"scorer {scorer['id']} check {check_id} evidence reference does not match the scoring contract")
        checks.append({
            "id": check_id,
            "passed": passed,
            "max_points": maximum,
            "earned_points": round(earned, 4),
            "partial_credit": partial,
            "evidence_reference": evidence,
            "detail": str(item.get("detail", "")),
        })
        earned_total += earned
    if abs(float(dimension["max_points"]) - float(scorer["max_points"])) > 1e-9:
        raise WorkflowError(f"scorer {scorer['id']} maximum does not match the scoring contract")
    return checks, round(earned_total, 4)


def _run_scorer(
    plan: Mapping[str, Any],
    pair: Mapping[str, Any],
    arm: Mapping[str, Any],
    scorer: Mapping[str, Any],
    contract: Mapping[str, Any] | None = None,
    scoring_bundle: Path | None = None,
) -> dict[str, Any]:
    stage = Path(arm["stage_dir"])
    scores_dir = stage / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)
    result_path = scores_dir / f"{scorer['id']}.json"
    suite = Path(plan["coordinator"]["suite_dir"])
    values = {
        "run_id": str(plan["run_id"]),
        "pair_id": str(pair["pair_id"]),
        "case_id": str(pair["case_id"]),
        "arm": str(arm["arm"]),
        "worktree": str(arm["worktree"]),
        "stage_dir": str(stage),
        "scores_dir": str(scores_dir),
        "result_file": str(result_path),
        "suite": str(suite),
        "max_points": str(scorer["max_points"]),
        "dimension": str(scorer["dimension"]),
        "scorer_id": str(scorer["id"]),
        "scoring_contract": str(suite / str(plan.get("scoring_identity", {}).get("contract_path", "scoring-contract.json"))),
        "scoring_bundle": str(scoring_bundle) if scoring_bundle is not None else "",
    }
    template_text = "\n".join(str(item) for item in scorer["argv"])
    if "{scoring_bundle}" in template_text and scoring_bundle is None:
        raise WorkflowError(
            f"scorer {scorer['id']} requires an external scoring bundle; "
            "pass --scoring-bundle after the execution is sealed"
        )
    argv = format_argv(scorer["argv"], values)
    process = run(
        argv,
        cwd=Path(arm["worktree"]),
        check=False,
        timeout_seconds=float(scorer["timeout_seconds"]),
        max_stdout_bytes=4 * 1024 * 1024,
        max_stderr_bytes=4 * 1024 * 1024,
        environment=EnvironmentPolicy(
            allowlist=tuple(plan["executor"].get("environment_allowlist", [])),
            values={
                "AGENT_WORKFLOW_BENCHMARK_SCORER": str(scorer["id"]),
                "AGENT_WORKFLOW_BENCHMARK_RESULT_FILE": str(result_path),
            },
            unsafe_inherit=bool(plan["executor"].get("unsafe_inherit_environment", False)),
        ),
        digest_executable=True,
    )
    (scores_dir / f"{scorer['id']}.stdout.log").write_text(str(process.stdout), encoding="utf-8")
    (scores_dir / f"{scorer['id']}.stderr.log").write_text(str(process.stderr), encoding="utf-8")
    if not result_path.is_file():
        return {
            "id": scorer["id"],
            "dimension": scorer["dimension"],
            "max_points": scorer["max_points"],
            "earned_points": 0.0,
            "state": "harness_failure",
            "details": [f"scorer produced no result file; returncode={process.returncode}"],
            "result_sha256": None,
            "duration_seconds": process.duration_seconds,
        }
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid scorer result {result_path}: {exc}") from exc
    if not isinstance(result, dict):
        raise WorkflowError(f"scorer result must be an object: {result_path}")
    maximum = float(scorer["max_points"])
    if contract is not None:
        checks, earned = _contract_checks(scorer, result, contract)
        claimed = result.get("earned_points")
        if isinstance(claimed, bool) or not isinstance(claimed, (int, float)):
            raise WorkflowError(f"scorer {scorer['id']} did not provide numeric earned_points")
        if abs(float(claimed) - earned) > 1e-9:
            raise WorkflowError(f"scorer {scorer['id']} earned_points do not equal contracted check points")
    else:
        earned = result.get("earned_points")
        if isinstance(earned, bool) or not isinstance(earned, (int, float)):
            raise WorkflowError(f"scorer {scorer['id']} did not provide numeric earned_points")
        if earned < 0 or earned > maximum:
            raise WorkflowError(f"scorer {scorer['id']} points {earned} exceed 0..{maximum}")
        checks = result.get("checks", [])
    return {
        "id": scorer["id"],
        "dimension": scorer["dimension"],
        "max_points": maximum,
        "earned_points": round(float(earned), 4),
        "state": str(result.get("state", "pass" if earned == maximum else ("partial" if earned else "fail"))),
        "details": [str(item) for item in result.get("details", [])],
        "checks": checks,
        "result_sha256": sha256_file(result_path),
        "duration_seconds": process.duration_seconds,
    }


def _observed_machine_score(components: list[Mapping[str, Any]]) -> float:
    """Sum completed scorer observations without applying eligibility policy."""
    return round(sum(float(item["earned_points"]) for item in components), 4)


def score_run(
    plan_path: Path,
    *,
    scoring_bundle: Path | None = None,
) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    plan = read_object(plan_path)
    run_dir = Path(plan["coordinator"]["run_dir"])
    summary_path = run_dir / "machine-scores.json"
    if summary_path.is_file():
        return read_object(summary_path)
    require_execution_seal(plan_path)
    if scoring_bundle is not None:
        scoring_bundle = scoring_bundle.expanduser().resolve()
        if not scoring_bundle.is_dir():
            raise WorkflowError(f"scoring bundle directory not found: {scoring_bundle}")
    spec_path = Path(plan["coordinator"]["spec_path"])
    spec = validate_spec(spec_path)
    contract = load_scoring_contract(spec_path, spec)
    supplementary_contract = load_supplementary_scoring_contract(spec_path, spec)
    supplementary_contract_path = spec_path.parent / "product-scoring-contract.json"
    append_event(run_dir, event_type="machine_scoring_started", run_id=str(plan["run_id"]))
    scored: list[dict[str, Any]] = []
    supplementary_scored: list[dict[str, Any]] = []
    for pair in plan["pairs"]:
        pair_state_path = run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / "pair.json"
        if not pair_state_path.is_file():
            raise WorkflowError(f"pair execution evidence missing: {pair_state_path}")
        pair_state = read_object(pair_state_path)
        arms = selected_arms(pair, pair_state)
        selected_pair = {**pair, "arms": arms}
        for arm_name in ("control_raw", "workflow_full"):
            arm = arms[arm_name]
            stage = Path(arm["stage_dir"])
            arm_value = read_object(stage / "arm.json")
            capture_path = stage / "visual" / "capture.json"
            capture = read_object(capture_path) if capture_path.is_file() else None
            guardrails = _core_guardrails(plan, selected_pair, pair_state, arm_value, capture, spec)
            components = [
                _run_scorer(
                    plan,
                    pair,
                    arm,
                    item,
                    contract,
                    scoring_bundle=scoring_bundle,
                )
                for item in spec["machine_scoring"]["scorers"]
            ]
            required_failures = [
                item["id"]
                for item in guardrails
                if item["required"] and item["state"] != "pass"
            ]
            scorer_harness_failures = [item["id"] for item in components if item["state"] == "harness_failure"]
            eligible = not required_failures and not scorer_harness_failures
            # A guardrail determines whether a result may qualify for a winner;
            # it must not erase the score produced by completed scorers.  Keep
            # the observed score for diagnostics and reporting, while the
            # eligibility projection remains the authority for composites.
            score = _observed_machine_score(components)
            score_schema = BENCHMARK_MACHINE_SCORE_V2_SCHEMA if contract is not None else BENCHMARK_MACHINE_SCORE_SCHEMA
            value = {
                "schema": score_schema,
                "run_id": plan["run_id"],
                "benchmark_id": plan["benchmark_id"],
                "pair_id": pair["pair_id"],
                "case_id": pair["case_id"],
                "repetition": pair["repetition"],
                "arm": arm_name,
                "eligibility": {
                    "state": "eligible" if eligible else "invalid",
                    "required_failures": required_failures,
                    "scorer_harness_failures": scorer_harness_failures,
                    "guardrails": guardrails,
                    "publication_eligible": eligible
                    and bool(plan["executor"]["sandbox"].get("verified_isolation"))
                    and isinstance(capture, Mapping)
                    and capture.get("runtime_state") == "publication-verified",
                },
                "machine_score": score,
                "maximum_score": 100.0,
                "components": components,
                "verification_wall_seconds": round(
                    sum(float(item["duration_seconds"]) for item in components), 6
                ),
                "scored_at": utc_now(),
            }
            if contract is not None:
                suite = Path(plan["coordinator"]["suite_dir"])
                contract_path = suite / str(spec["scoring_contract_path"])
                evaluator_ref = str(contract["evaluator_path"])
                evaluator_sha256 = None
                if evaluator_ref.startswith("external://"):
                    if scoring_bundle is None:
                        raise WorkflowError(
                            "external scoring evaluator requires --scoring-bundle"
                        )
                    evaluator_path = scoring_bundle / evaluator_ref.removeprefix("external://")
                    if not evaluator_path.is_file():
                        raise WorkflowError(
                            f"external scoring evaluator not found: {evaluator_path}"
                        )
                    evaluator_sha256 = sha256_file(evaluator_path)
                else:
                    evaluator_sha256 = sha256_file(suite / evaluator_ref)
                value.update(
                    benchmark_version=spec["version"],
                    scoring_identity={
                        "scorer_version": contract["scorer_version"],
                        "evaluator_version": contract["evaluator_version"],
                        "scoring_contract_sha256": sha256_file(contract_path),
                        "evaluator_ref": evaluator_ref,
                        "evaluator_sha256": evaluator_sha256,
                    },
                )
            validate_value(value, score_schema, f"machine score {pair['pair_id']} {arm_name}")
            atomic_write_json(stage / "score.json", value)
            scored.append(value)
            if supplementary_contract is not None:
                try:
                    product = score_end_to_end_product(
                        worktree=Path(arm["worktree"]),
                        stage=stage,
                        machine_components=components,
                        contract=supplementary_contract,
                        contract_path=supplementary_contract_path,
                    )
                except Exception as exc:
                    product = {
                        "schema": BENCHMARK_SUPPLEMENTARY_SCORE_SCHEMA,
                        "id": str(supplementary_contract["id"]),
                        "role": "supplementary",
                        "winner_interaction": "none",
                        "state": "unavailable",
                        "score": None,
                        "maximum_score": 100,
                        "contract_sha256": sha256_file(supplementary_contract_path),
                        "scorer_version": str(supplementary_contract["scorer_version"]),
                        "dimensions": [],
                        "limitations": [
                            *[str(item) for item in supplementary_contract.get("limitations", [])],
                            "Supplementary score unavailable; official machine scoring remains authoritative.",
                        ],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                validate_value(
                    product,
                    BENCHMARK_SUPPLEMENTARY_SCORE_SCHEMA,
                    f"supplementary score {pair['pair_id']} {arm_name}",
                )
                atomic_write_json(stage / "product-score.json", product)
                supplementary_scored.append({
                    "pair_id": pair["pair_id"],
                    "case_id": pair["case_id"],
                    "repetition": pair["repetition"],
                    "arm": arm_name,
                    "score": product,
                })
    summary = {
        "schema": "agent-workflow/benchmark-machine-score-set/v1",
        "run_id": plan["run_id"],
        "scores": scored,
        "eligible": sum(1 for item in scored if item["eligibility"]["state"] == "eligible"),
        "invalid": sum(1 for item in scored if item["eligibility"]["state"] != "eligible"),
        "supplementary_scores": supplementary_scored,
        "scoring_bundle": (
            {
                "path": str(scoring_bundle),
                "tree_sha256": tree_sha256(scoring_bundle),
            }
            if scoring_bundle is not None
            else None
        ),
    }
    atomic_write_json(run_dir / "machine-scores.json", summary)
    append_event(
        run_dir,
        event_type="machine_scoring_terminal",
        run_id=str(plan["run_id"]),
        payload={
            "eligible": summary["eligible"],
            "invalid": summary["invalid"],
            "supplementary_scored": sum(
                1 for item in supplementary_scored if item["score"].get("state") == "scored"
            ),
            "supplementary_unavailable": sum(
                1 for item in supplementary_scored if item["score"].get("state") != "scored"
            ),
        },
    )
    return summary
