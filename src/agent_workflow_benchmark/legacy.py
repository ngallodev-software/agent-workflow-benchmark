from __future__ import annotations
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from agent_workflow.errors import WorkflowError
from agent_workflow.eval.compare import compare_trials
from agent_workflow.eval.trials import load_trials
from .benchmarking.schema_contracts import read_contract, validate_instance

BENCHMARK_MANIFEST_SCHEMA="agent-workflow/benchmark-manifest/v1"
BENCHMARK_REPORT_SCHEMA="agent-workflow/benchmark-report/v1"
IDENTITY_FIELDS=(
    ("provider","provider"),("source_revision","source_revision"),("pack_manifest_sha256","pack_manifest_sha256"),
    ("model","model"),("executor","executor"),("executor_version","executor_version"),
)

def _safe_relative(value: str, label: str) -> None:
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if value.endswith("/"):
        normalized += "/"
    if (
        path.is_absolute()
        or not value
        or "\\" in value
        or value != normalized
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise WorkflowError(
            f"{label} must be a normalized relative path: {value!r}"
        )

def validate_benchmark_manifest(
    path: Path, *, pack_root: Path | None = None
) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if pack_root is not None:
        root = pack_root.expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise WorkflowError(f"benchmark manifest escapes pack root: {path}") from exc
    value = read_contract(path, BENCHMARK_MANIFEST_SCHEMA)
    cases = value["cases"]
    case_ids = [str(item["case_id"]) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise WorkflowError("benchmark manifest contains duplicate case IDs")
    trial_keys = [
        (str(item["task_id"]), int(item["repetition"])) for item in cases
    ]
    if len(trial_keys) != len(set(trial_keys)):
        raise WorkflowError(
            "benchmark manifest contains duplicate task/repetition identities"
        )
    for case in cases:
        case_id = str(case["case_id"])
        for key in ("writable_paths", "writable_trees", "disposable_trees"):
            for relative in case["allowed_writable_scope"].get(key, []):
                _safe_relative(str(relative), f"case {case_id} {key}")
        availability = case["availability"]
        expected_class = case["expected_evidence_class"]
        if availability["state"] == "available":
            if availability.get("reason") is not None:
                raise WorkflowError(
                    f"available benchmark case {case_id} must not declare an unavailable reason"
                )
            if expected_class == "unavailable":
                raise WorkflowError(
                    f"available benchmark case {case_id} cannot expect unavailable evidence"
                )
        else:
            if not availability.get("reason"):
                raise WorkflowError(
                    f"unavailable benchmark case {case_id} requires a reason"
                )
            if expected_class != "unavailable":
                raise WorkflowError(
                    f"unavailable benchmark case {case_id} must use expected evidence class 'unavailable'"
                )
    return value

def _trial_summary(trial: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if trial is None:
        return None
    return {
        "trial_id": trial.get("trial_id"),
        "verdict": trial.get("verdict"),
        "duration_seconds": trial.get("duration_seconds"),
        "tokens": trial.get("tokens"),
        "input_tokens": trial.get("input_tokens"),
        "cached_input_tokens": trial.get("cached_input_tokens"),
        "output_tokens": trial.get("output_tokens"),
        "provider_billed_cost": trial.get("provider_billed_cost"),
        "local_estimated_cost": trial.get("local_estimated_cost"),
        "currency": trial.get("currency"),
        "price_catalog_id": trial.get("price_catalog_id"),
        "final_receipt_sha256": trial.get("final_receipt_sha256"),
        "errors": trial.get("errors", []),
    }

def _index_trials(
    role: str, trials: Sequence[dict[str, Any]]
) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for trial in trials:
        key = (str(trial.get("task_id")), int(trial.get("repetition") or 0))
        if key in result:
            raise WorkflowError(f"duplicate {role} benchmark trial identity: {key}")
        result[key] = trial
    return result

def _cohort_identity(
    role: str,
    expected: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verified: list[str] = []
    unverified: list[str] = []
    for manifest_field, trial_field in IDENTITY_FIELDS:
        expected_value = expected.get(manifest_field)
        actual_values = [trial.get(trial_field) for trial in trials]
        non_null = {item for item in actual_values if item is not None}
        if len(non_null) > 1:
            raise WorkflowError(
                f"{role} cohort {manifest_field} is not homogeneous: "
                f"{sorted(str(item) for item in non_null)}"
            )
        if expected_value is None:
            unverified.append(manifest_field)
            continue
        contradictions = sorted(
            str(item) for item in non_null if item != expected_value
        )
        if contradictions:
            raise WorkflowError(
                f"{role} cohort {manifest_field} mismatch: "
                f"expected {expected_value!r}, observed {contradictions}"
            )
        if not actual_values or any(item is None for item in actual_values):
            unverified.append(manifest_field)
        else:
            verified.append(manifest_field)
    return {
        "state": "verified" if not unverified else "not_verified",
        "verified_fields": sorted(verified),
        "unverified_fields": sorted(unverified),
    }

def _require_match(
    *,
    role: str,
    case_id: str,
    field: str,
    expected: Any,
    actual: Any,
    missing: list[str],
) -> None:
    if expected is None:
        return
    if actual is None:
        missing.append(field)
        return
    if actual != expected:
        raise WorkflowError(
            f"{role} case {case_id} {field} mismatch: "
            f"expected {expected!r}, observed {actual!r}"
        )

def _validate_case_trial(
    role: str, case: Mapping[str, Any], trial: Mapping[str, Any]
) -> list[str]:
    case_id = str(case["case_id"])
    missing: list[str] = []
    _require_match(
        role=role,
        case_id=case_id,
        field="prompt_sha256",
        expected=case.get("prompt_sha256"),
        actual=trial.get("prompt_sha256"),
        missing=missing,
    )
    source_artifacts = trial.get("source_artifacts")
    artifacts = source_artifacts if isinstance(source_artifacts, Mapping) else {}
    _require_match(
        role=role,
        case_id=case_id,
        field="input_sha256",
        expected=case.get("input_sha256"),
        actual=artifacts.get("workflow-inputs.json"),
        missing=missing,
    )
    fixture = case.get("fixture_provenance")
    if isinstance(fixture, Mapping):
        _require_match(
            role=role,
            case_id=case_id,
            field="fixture_revision",
            expected=fixture.get("revision"),
            actual=trial.get("fixture_revision"),
            missing=missing,
        )
        _require_match(
            role=role,
            case_id=case_id,
            field="fixture_sha256",
            expected=fixture.get("sha256"),
            actual=trial.get("fixture_sha256"),
            missing=missing,
        )
    oracle = case.get("oracle")
    if isinstance(oracle, Mapping):
        _require_match(
            role=role,
            case_id=case_id,
            field="oracle_sha256",
            expected=oracle.get("sha256"),
            actual=trial.get("oracle_sha256"),
            missing=missing,
        )
    reference = case.get("reference")
    if isinstance(reference, Mapping):
        _require_match(
            role=role,
            case_id=case_id,
            field="reference_sha256",
            expected=reference.get("sha256"),
            actual=trial.get("reference_sha256"),
            missing=missing,
        )
    for manifest_field, trial_field in IDENTITY_FIELDS:
        expected = case.get("_cohort", {}).get(manifest_field)
        _require_match(
            role=role,
            case_id=case_id,
            field=manifest_field,
            expected=expected,
            actual=trial.get(trial_field),
            missing=missing,
        )
    return sorted(set(missing))

def build_benchmark_report(
    manifest_path: Path,
    baseline_path: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    baseline_path = baseline_path.expanduser().resolve()
    candidate_path = candidate_path.expanduser().resolve()
    manifest = validate_benchmark_manifest(manifest_path)
    baseline = load_trials(baseline_path)
    candidate = load_trials(candidate_path)

    baseline_identity = _cohort_identity(
        "baseline", manifest["cohorts"]["baseline"], baseline
    )
    candidate_identity = _cohort_identity(
        "candidate", manifest["cohorts"]["candidate"], candidate
    )
    left = _index_trials("baseline", baseline)
    right = _index_trials("candidate", candidate)

    case_rows: list[dict[str, Any]] = []
    complete_baseline: list[dict[str, Any]] = []
    complete_candidate: list[dict[str, Any]] = []
    missing_baseline = 0
    missing_candidate = 0
    unverified_baseline = 0
    unverified_candidate = 0
    unavailable = 0
    regressions: list[str] = []
    manifest_keys: set[tuple[str, int]] = set()

    for original_case in sorted(manifest["cases"], key=lambda item: item["case_id"]):
        role_expectations = manifest["cohorts"]
        case = dict(original_case)
        key = (str(case["task_id"]), int(case["repetition"]))
        manifest_keys.add(key)
        before = left.get(key)
        after = right.get(key)
        if case["availability"]["state"] == "unavailable":
            if before is not None or after is not None:
                raise WorkflowError(
                    f"unavailable benchmark case {case['case_id']} has trial evidence"
                )
            unavailable += 1
            case_rows.append(
                {
                    "case_id": case["case_id"],
                    "task_id": case["task_id"],
                    "repetition": case["repetition"],
                    "expected_evidence_class": case["expected_evidence_class"],
                    "state": "unavailable",
                    "unavailable_reason": case["availability"].get("reason"),
                    "baseline": None,
                    "candidate": None,
                    "missing_evidence": {"baseline": [], "candidate": []},
                    "regression": False,
                }
            )
            continue

        baseline_missing: list[str] = []
        candidate_missing: list[str] = []
        if before is None:
            missing_baseline += 1
            baseline_missing.append("trial")
        else:
            case["_cohort"] = role_expectations["baseline"]
            baseline_missing.extend(_validate_case_trial("baseline", case, before))
        if after is None:
            missing_candidate += 1
            candidate_missing.append("trial")
        else:
            case["_cohort"] = role_expectations["candidate"]
            candidate_missing.extend(_validate_case_trial("candidate", case, after))
        baseline_missing = sorted(set(baseline_missing))
        candidate_missing = sorted(set(candidate_missing))
        if before is not None and baseline_missing:
            unverified_baseline += 1
        if after is not None and candidate_missing:
            unverified_candidate += 1
        complete = bool(
            before is not None
            and after is not None
            and not baseline_missing
            and not candidate_missing
        )
        if complete:
            complete_baseline.append(before)
            complete_candidate.append(after)
        regression = bool(
            complete
            and before.get("verdict") == "pass"
            and after.get("verdict") != "pass"
        )
        if regression:
            regressions.append(str(case["case_id"]))
        case_rows.append(
            {
                "case_id": case["case_id"],
                "task_id": case["task_id"],
                "repetition": case["repetition"],
                "expected_evidence_class": case["expected_evidence_class"],
                "state": "complete" if complete else "not_verified",
                "unavailable_reason": None,
                "baseline": _trial_summary(before),
                "candidate": _trial_summary(after),
                "missing_evidence": {
                    "baseline": baseline_missing,
                    "candidate": candidate_missing,
                },
                "regression": regression,
            }
        )

    unmatched_baseline = sorted(
        str(trial.get("trial_id"))
        for key, trial in left.items()
        if key not in manifest_keys
    )
    unmatched_candidate = sorted(
        str(trial.get("trial_id"))
        for key, trial in right.items()
        if key not in manifest_keys
    )
    comparison = compare_trials(complete_baseline, complete_candidate)
    report = {
        "schema": BENCHMARK_REPORT_SCHEMA,
        "benchmark_id": manifest["benchmark_id"],
        "manifest_sha256": sha256_file(manifest_path),
        "baseline": {
            **manifest["cohorts"]["baseline"],
            "trial_collection_sha256": sha256_file(baseline_path),
            "trial_count": len(baseline),
            "selected_trial_count": len(complete_baseline),
            "identity_verification": baseline_identity,
        },
        "candidate": {
            **manifest["cohorts"]["candidate"],
            "trial_collection_sha256": sha256_file(candidate_path),
            "trial_count": len(candidate),
            "selected_trial_count": len(complete_candidate),
            "identity_verification": candidate_identity,
        },
        "cases": case_rows,
        "aggregate_metrics": comparison,
        "missingness": {
            "unavailable_case_count": unavailable,
            "missing_baseline_count": missing_baseline,
            "missing_candidate_count": missing_candidate,
            "unverified_baseline_count": unverified_baseline,
            "unverified_candidate_count": unverified_candidate,
            "unmatched_baseline_count": len(unmatched_baseline),
            "unmatched_candidate_count": len(unmatched_candidate),
            "null_metric_policy": "preserve-null",
        },
        "unmatched_trials": {
            "baseline": unmatched_baseline,
            "candidate": unmatched_candidate,
        },
        "regressions": sorted(regressions),
        "reproducible_commands": [
            "agent-workflow benchmark legacy-validate <manifest.json>",
            "agent-workflow benchmark legacy-report <manifest.json> <baseline.json> <candidate.json> --output <report.json>",
        ],
    }
    validate_instance(report, BENCHMARK_REPORT_SCHEMA, artifact="benchmark report")
    return report

def render_benchmark_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        f"# Benchmark report: {report['benchmark_id']}",
        "",
        f"- Baseline cohort: `{report['baseline']['cohort_id']}`",
        f"- Candidate cohort: `{report['candidate']['cohort_id']}`",
        f"- Paired verified cases: {aggregate['paired_n']}",
        f"- Winner: `{aggregate['winner'] or 'not-established'}`",
        f"- Unavailable cases: {report['missingness']['unavailable_case_count']}",
        f"- Not-verified baseline cases: {report['missingness']['missing_baseline_count'] + report['missingness']['unverified_baseline_count']}",
        f"- Not-verified candidate cases: {report['missingness']['missing_candidate_count'] + report['missingness']['unverified_candidate_count']}",
        f"- Unmatched baseline trials: {report['missingness']['unmatched_baseline_count']}",
        f"- Unmatched candidate trials: {report['missingness']['unmatched_candidate_count']}",
        f"- Regressions: {len(report['regressions'])}",
        "",
        "## Case results",
        "",
        "| Case | State | Baseline | Candidate | Missing evidence | Regression |",
        "|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        before = case["baseline"]["verdict"] if case["baseline"] else "unavailable"
        after = case["candidate"]["verdict"] if case["candidate"] else "unavailable"
        missing = case["missing_evidence"]
        missing_text = "; ".join(
            f"{role}: {', '.join(values)}"
            for role, values in (("baseline", missing["baseline"]), ("candidate", missing["candidate"]))
            if values
        ) or "none"
        lines.append(
            f"| {case['case_id']} | {case['state']} | {before} | {after} | "
            f"{missing_text} | {'yes' if case['regression'] else 'no'} |"
        )
    lines.extend(["", "## Reproducible commands", ""])
    lines.extend(f"- `{command}`" for command in report["reproducible_commands"])
    return "\n".join(lines) + "\n"
