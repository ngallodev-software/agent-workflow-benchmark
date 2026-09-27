from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

import agent_workflow_comparative_eval as comparative
from agent_workflow import __version__ as agent_workflow_version
from agent_workflow.comparative_eval_runtime import routing_comparison_records
from agent_workflow.config import Settings
from agent_workflow.decisions import require_decision_runtime_ready
from agent_workflow.errors import WorkflowError
from agent_workflow.routing import advise_routing_with_policy
from agent_workflow.util import atomic_write_bytes, atomic_write_json, sha256_file

from agent_workflow_benchmark import __version__ as benchmark_version
from .common import file_inventory, write_manifest
from .schema_contracts import read_contract, validate_instance

CORPUS_SCHEMA = comparative.DECISION_STUDY_CORPUS_SCHEMA
ORACLE_BUNDLE_SCHEMA = comparative.DECISION_STUDY_ORACLE_BUNDLE_SCHEMA
RUN_SCHEMA = "agent-workflow-benchmark/decision-study-run/v1"
PUBLICATION_SCHEMA = "agent-workflow-benchmark/decision-study-publication/v1"

_OBSERVATIONS = "observations.jsonl"
_REQUESTS = "provider-requests.jsonl"
_EXCLUSIONS = "exclusions.jsonl"
_OUTCOMES = "outcomes.jsonl"
_REPORT = "decision-study-report.json"
_REPORT_MD = "decision-study-report.md"
_RUN = "run-manifest.json"
_CORPUS = "corpus.json"
_STUDY_SPEC = "study-spec.json"

_RESERVED_INFERENCE_KEYS = frozenset(
    {"oracle", "ground_truth", "labels", "adjudication", "expected_answer"}
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid JSONL in {path} line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkflowError(f"expected object in {path} line {line_number}")
        result.append(value)
    return result


def _write_jsonl(path: Path, records: list[Mapping[str, Any]]) -> None:
    payload = "".join(
        json.dumps(dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for record in records
    )
    atomic_write_bytes(path, payload.encode("utf-8"))


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid decision-study contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"decision-study contract must be an object: {path}")
    return value


def _contains_reserved_key(value: Any, *, path: str = "metadata") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            current = f"{path}.{key}"
            if normalized in _RESERVED_INFERENCE_KEYS:
                return current
            nested = _contains_reserved_key(item, path=current)
            if nested:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = _contains_reserved_key(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return None


def _load_corpus(path: Path, study: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        corpus = comparative.validate_decision_study_corpus(_read_json_object(Path(path)))
    except (ValueError, comparative.ContractError) as exc:
        raise WorkflowError(f"invalid decision-study corpus {path}: {exc}") from exc
    spec = comparative.load_study_spec(study)
    if corpus["study_id"] != spec["study_id"]:
        raise WorkflowError(
            f"corpus study_id {corpus['study_id']!r} does not match {spec['study_id']!r}"
        )
    case_ids: set[str] = set()
    for index, case in enumerate(corpus["cases"]):
        if not isinstance(case, Mapping):
            raise WorkflowError(f"corpus case {index} must be an object")
        comparative.validate_record(case, comparative.DECISION_STUDY_CASE_SCHEMA)
        case_id = str(case["case_id"])
        if case_id in case_ids:
            raise WorkflowError(f"duplicate decision-study case ID: {case_id}")
        case_ids.add(case_id)
        if case["dataset_version"] != corpus["dataset_version"]:
            raise WorkflowError(
                f"case {case_id} dataset_version differs from corpus dataset_version"
            )
        leaked = _contains_reserved_key(case.get("metadata", {}))
        if leaked:
            raise WorkflowError(
                f"inference corpus contains oracle-like key at {case_id}:{leaked}"
            )
    return corpus, spec


def _load_oracle(
    path: Path, *, study_id: str, dataset_version: str, cases: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    try:
        bundle = comparative.validate_decision_study_oracle_bundle(
            _read_json_object(Path(path)),
            expected_study_id=study_id,
            expected_dataset_version=dataset_version,
        )
    except (ValueError, comparative.ContractError) as exc:
        raise WorkflowError(f"invalid decision-study oracle bundle {path}: {exc}") from exc
    records: dict[str, Mapping[str, Any]] = {}
    for raw in bundle["records"]:
        comparative.validate_record(raw, comparative.DECISION_STUDY_ORACLE_SCHEMA)
        case_id = str(raw["case_id"])
        if case_id not in cases:
            raise WorkflowError(f"oracle contains unknown case ID: {case_id}")
        if case_id in records:
            raise WorkflowError(f"oracle contains duplicate case ID: {case_id}")
        if raw["dataset_version"] != dataset_version:
            raise WorkflowError(f"oracle record {case_id} has a different dataset version")
        records[case_id] = raw
    return {**bundle, "records_by_case": records}


def _required_decisions(spec: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(item["decision_id"]) for item in spec["decision_seams"])


def _required_features(spec: Mapping[str, Any]) -> set[str]:
    return {str(item["feature_id"]) for item in spec["decision_seams"]}


def _case_map(corpus: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(case["case_id"]): case for case in corpus["cases"]}


def _write_export(path: Path, value: Mapping[str, Any], *, force: bool) -> dict[str, Any]:
    path = Path(path)
    if path.exists() and not force:
        raise WorkflowError(f"decision-study export already exists: {path}")
    if path.exists() and (path.is_dir() or path.is_symlink()):
        raise WorkflowError(f"decision-study export must be a regular file path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(value))
    return {"path": str(path), "sha256": sha256_file(path)}


def export_decision_study_corpus(
    destination: Path,
    *,
    study: str = "routing-semantic-v1",
    force: bool = False,
) -> dict[str, Any]:
    corpus = comparative.load_study_corpus(study)
    result = _write_export(Path(destination), corpus, force=force)
    result.update(
        {
            "study_id": corpus["study_id"],
            "dataset_version": corpus["dataset_version"],
            "cases": len(corpus["cases"]),
        }
    )
    return result


def export_oracle_authoring_view(
    destination: Path,
    *,
    study: str = "routing-semantic-v1",
    force: bool = False,
) -> dict[str, Any]:
    corpus = comparative.load_study_corpus(study)
    view = comparative.oracle_authoring_view(corpus)
    result = _write_export(Path(destination), view, force=force)
    result.update(
        {
            "study_id": view["study_id"],
            "dataset_version": view["dataset_version"],
            "cases": len(view["cases"]),
            "construction_tags_included": view["blinding"]["construction_tags_included"],
        }
    )
    return result


def validate_decision_study(
    corpus_path: Path,
    *,
    study: str = "routing-semantic-v1",
    oracle_path: Path | None = None,
) -> dict[str, Any]:
    corpus, spec = _load_corpus(Path(corpus_path), study)
    cases = _case_map(corpus)
    result: dict[str, Any] = {
        "valid": True,
        "study_id": spec["study_id"],
        "study_version": spec["study_version"],
        "dataset_version": corpus["dataset_version"],
        "cases": len(cases),
        "oracle": None,
        "corpus_sha256": sha256_file(Path(corpus_path)),
    }
    if oracle_path is not None:
        oracle = _load_oracle(
            Path(oracle_path),
            study_id=str(spec["study_id"]),
            dataset_version=str(corpus["dataset_version"]),
            cases=cases,
        )
        missing: dict[str, list[str]] = {}
        unresolved: dict[str, list[str]] = {}
        for case_id, case in cases.items():
            eligible = case["oracle_eligible"]
            record = oracle["records_by_case"].get(case_id)
            labels = record.get("labels", {}) if isinstance(record, Mapping) else {}
            adjudication = (
                record.get("adjudication", {})
                if isinstance(record, Mapping)
                else {}
            )
            for decision_id in _required_decisions(spec):
                if eligible[decision_id] is not True or decision_id in labels:
                    continue
                seam_adjudication = (
                    adjudication.get(decision_id, {})
                    if isinstance(adjudication, Mapping)
                    else {}
                )
                if (
                    isinstance(seam_adjudication, Mapping)
                    and seam_adjudication.get("status")
                    == "oracle_conflict_unresolved"
                ):
                    unresolved.setdefault(case_id, []).append(decision_id)
                else:
                    missing.setdefault(case_id, []).append(decision_id)
        if missing:
            detail = "; ".join(
                f"{case_id}: {','.join(decisions)}"
                for case_id, decisions in sorted(missing.items())
            )
            raise WorkflowError(f"oracle is incomplete for eligible cases: {detail}")
        result["oracle"] = {
            "records": len(oracle["records_by_case"]),
            "oracle_version": oracle["oracle_version"],
            "sha256": sha256_file(Path(oracle_path)),
            "frozen": oracle["frozen"],
            "unresolved_conflicts": sum(len(items) for items in unresolved.values()),
        }
    return result


def _semantic_identity(
    settings: Settings,
    advice: Mapping[str, Any],
    *,
    study_id: str,
    study_version: str,
    dataset_version: str,
) -> dict[str, Any]:
    receipts = advice.get("decision_receipts")
    semantic: Mapping[str, Any] = {}
    if isinstance(receipts, Mapping):
        first = receipts.get("routing.task_class")
        if isinstance(first, Mapping) and isinstance(first.get("semantic"), Mapping):
            semantic = first["semantic"]
    try:
        sdk_version = metadata.version("typesafe-sdk")
    except metadata.PackageNotFoundError:
        sdk_version = None
    return {
        "study_id": study_id,
        "study_version": study_version,
        "dataset_version": dataset_version,
        "agent_workflow_version": agent_workflow_version,
        "benchmark_version": benchmark_version,
        "comparative_eval_version": comparative.__version__,
        "decision_mode": settings.decision_mode,
        "decision_profile": settings.decision_profile,
        "provider": "typesafe",
        "model": semantic.get("model"),
        "typesafe_sdk_version": sdk_version,
        "question_set_version": semantic.get("question_set_version"),
        "projector_version": semantic.get("projector_version"),
    }


def run_decision_study(
    settings: Settings,
    corpus_path: Path,
    output: Path,
    *,
    study: str = "routing-semantic-v1",
    force: bool = False,
) -> dict[str, Any]:
    corpus, spec = _load_corpus(Path(corpus_path), study)
    if settings.decision_mode != "comparative":
        raise WorkflowError(
            "decision-study run requires decision_policy.mode='comparative'"
        )
    require_decision_runtime_ready(settings)

    output = Path(output).resolve()
    if output.exists():
        if not force:
            raise WorkflowError(f"decision-study output already exists: {output}")
        if output.is_symlink() or not output.is_dir():
            raise WorkflowError(f"refusing to replace non-directory output: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    started = _utc()
    atomic_write_json(output / _STUDY_SPEC, spec)
    atomic_write_json(output / _CORPUS, corpus)

    observations: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    request_ids: set[str] = set()

    for case in corpus["cases"]:
        case_id = str(case["case_id"])
        try:
            advice = advise_routing_with_policy(
                case["metadata"],
                settings,
                task_text=str(case["task"]),
                source_ref=f"decision-study:{spec['study_id']}:{case_id}",
            )
        except WorkflowError as exc:
            exclusions.append(
                comparative.make_exclusion(
                    study_id=str(spec["study_id"]),
                    case_id=case_id,
                    reason_code="control_execution_failure",
                    stage="inference",
                    detail=type(exc).__name__,
                )
            )
            continue

        identity = _semantic_identity(
            settings,
            advice,
            study_id=str(spec["study_id"]),
            study_version=str(spec["study_version"]),
            dataset_version=str(corpus["dataset_version"]),
        )
        records = routing_comparison_records(
            advice=advice,
            identity=identity,
            source_input={"task": case["task"], "metadata": case["metadata"]},
            projected_input={
                "task": case["task"],
                "metadata": case["metadata"],
                "source_ref": f"decision-study:{spec['study_id']}:{case_id}",
            },
            case_id=case_id,
            observation_scope=(
                f"{spec['study_id']}:{corpus['dataset_version']}:{case_id}"
            ),
            mode="static",
            data_class="synthetic",
        )
        encoded = json.dumps(records["observations"], ensure_ascii=False)
        if str(case["task"]) in encoded:
            raise WorkflowError(
                "neutral comparative observation unexpectedly persisted raw task text"
            )
        request_id = str(records["request_id"])
        if request_id in request_ids:
            raise WorkflowError(
                f"provider request ID reused across study cases: {request_id}"
            )
        request_ids.add(request_id)
        observations.extend(records["observations"])
        requests.append(records["request"])

    _write_jsonl(output / _OBSERVATIONS, observations)
    _write_jsonl(output / _REQUESTS, requests)
    _write_jsonl(output / _EXCLUSIONS, exclusions)

    manifest = {
        "schema": RUN_SCHEMA,
        "study_id": spec["study_id"],
        "study_version": spec["study_version"],
        "dataset_version": corpus["dataset_version"],
        "started_at": started,
        "completed_at": _utc(),
        "identity": {
            "agent_workflow_version": agent_workflow_version,
            "benchmark_version": benchmark_version,
            "comparative_eval_version": comparative.__version__,
            "decision_mode": settings.decision_mode,
            "decision_profile": settings.decision_profile,
            "question_set_version": spec["frozen_runtime_identity"]["agent_workflow_question_set"],
            "projector_version": spec["frozen_runtime_identity"]["agent_workflow_projector"],
        },
        "counts": {
            "cases": len(corpus["cases"]),
            "observations": len(observations),
            "provider_requests": len(requests),
            "exclusions": len(exclusions),
        },
        "hashes": {
            "study_spec": sha256_file(output / _STUDY_SPEC),
            "corpus": sha256_file(output / _CORPUS),
            "observations": sha256_file(output / _OBSERVATIONS),
            "provider_requests": sha256_file(output / _REQUESTS),
            "exclusions": sha256_file(output / _EXCLUSIONS),
        },
        "files": {
            "study_spec": _STUDY_SPEC,
            "corpus": _CORPUS,
            "observations": _OBSERVATIONS,
            "provider_requests": _REQUESTS,
            "exclusions": _EXCLUSIONS,
        },
        "oracle_seen_during_inference": False,
    }
    validate_instance(manifest, RUN_SCHEMA, artifact="decision-study run manifest")
    atomic_write_json(output / _RUN, manifest)
    return {
        "run": str(output),
        "manifest": str(output / _RUN),
        "study_id": spec["study_id"],
        "dataset_version": corpus["dataset_version"],
        "cases": len(corpus["cases"]),
        "observations": len(observations),
        "provider_requests": len(requests),
        "exclusions": len(exclusions),
        "oracle_seen_during_inference": False,
    }


def _render_report(report: Mapping[str, Any], *, oracle_version: str) -> str:
    eligible = bool(report["eligibility"]["all_observed_seams_eligible"])
    lines = [
        "# Comparative Decision Study Report",
        "",
        f"- **Study:** {report['study_id']} / {report['study_version']}",
        f"- **Oracle:** {oracle_version}",
        f"- **Study sample eligible:** {'yes' if eligible else 'no'}",
        f"- **Provider requests:** {report['request_efficiency']['unique_requests']}",
        "",
        "## Per-seam results",
        "",
        "| Seam | n | Candidate metric | Control metric | Calibration |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for feature_id, seam in report["seams"].items():
        n = seam["counts"]["oracle_eligible"]
        semantic_type = seam.get("semantic_type")
        correctness = seam.get("correctness", {})
        if semantic_type in {"choice", "noul"} and "candidate_accuracy" in correctness:
            candidate = correctness["candidate_accuracy"]["rate"]
            control = correctness["control_accuracy"]["rate"]
            candidate_text = f"accuracy={candidate:.3f}" if candidate is not None else "n/a"
            control_text = f"accuracy={control:.3f}" if control is not None else "n/a"
        elif semantic_type == "score" and "candidate_ordinal" in correctness:
            candidate = correctness["candidate_ordinal"]["mean_absolute_error"]
            control = correctness["control_ordinal"]["mean_absolute_error"]
            candidate_text = f"MAE={candidate:.3f}" if candidate is not None else "n/a"
            control_text = f"MAE={control:.3f}" if control is not None else "n/a"
        else:
            candidate_text = control_text = "n/a"
        calibration = seam.get("calibration", {})
        if calibration.get("eligible"):
            normalization = calibration.get("probability_normalization", {})
            if (
                isinstance(normalization, Mapping)
                and normalization.get("applied") is True
            ):
                normalized = int(normalization.get("normalized_vectors", 0))
                total = int(normalization.get("total_vectors", 0))
                deviation = normalization.get("max_absolute_mass_deviation")
                deviation_text = (
                    f", max mass Δ={float(deviation):.6g}"
                    if isinstance(deviation, (int, float))
                    and not isinstance(deviation, bool)
                    else ""
                )
                calibration_text = (
                    f"eligible; normalized {normalized}/{total}{deviation_text}"
                )
            else:
                calibration_text = "eligible"
        else:
            calibration_text = "unavailable"
        lines.append(
            f"| {feature_id} | {n} | {candidate_text} | {control_text} | {calibration_text} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Agreement is not correctness; correctness in this report comes only from the separately frozen oracle. "
            "Provider latency/token evidence is counted once per batched request rather than once per decision seam.",
            "",
            "For Choice/Score calibration, finite nonnegative provider probability masses are normalized to unit sum only in the derived calibration calculation when needed; persisted raw evidence is unchanged and the per-seam table reports normalization use.",
            "",
            "A non-eligible development sample is useful for instrumentation validation but is not a generalized effectiveness claim.",
            "",
        ]
    )
    return "\n".join(lines)


def report_decision_study(
    run: Path,
    oracle_path: Path,
) -> dict[str, Any]:
    run = Path(run).resolve()
    manifest = read_contract(run / _RUN, RUN_SCHEMA)
    corpus = comparative.validate_decision_study_corpus(_read_json_object(run / _CORPUS))
    spec = json.loads((run / _STUDY_SPEC).read_text(encoding="utf-8"))
    comparative.validate_record(spec, comparative.DECISION_STUDY_SPEC_SCHEMA)
    cases = _case_map(corpus)
    oracle = _load_oracle(
        Path(oracle_path),
        study_id=str(manifest["study_id"]),
        dataset_version=str(manifest["dataset_version"]),
        cases=cases,
    )

    observations = _jsonl(run / _OBSERVATIONS)
    requests = _jsonl(run / _REQUESTS)
    exclusions = _jsonl(run / _EXCLUSIONS)
    outcomes: list[dict[str, Any]] = []

    for observation in observations:
        candidate = observation.get("candidate", {}).get("result")
        if not isinstance(candidate, Mapping):
            continue
        decision_id = str(candidate.get("decision_id") or "")
        case_id = str(observation.get("input", {}).get("case_id") or "")
        case = cases.get(case_id)
        if case is None:
            exclusions.append(
                comparative.make_exclusion(
                    study_id=str(manifest["study_id"]),
                    case_id=case_id or "unknown",
                    decision_id=decision_id or None,
                    reason_code="study_identity_mismatch",
                    stage="oracle-join",
                    detail="observation case_id absent from frozen corpus",
                )
            )
            continue
        eligible = case["oracle_eligible"].get(decision_id)
        if eligible is not True:
            continue
        oracle_record = oracle["records_by_case"].get(case_id)
        labels = (
            oracle_record.get("labels", {})
            if isinstance(oracle_record, Mapping)
            else {}
        )
        if decision_id not in labels:
            adjudication = (
                oracle_record.get("adjudication", {})
                if isinstance(oracle_record, Mapping)
                else {}
            )
            seam_adjudication = (
                adjudication.get(decision_id, {})
                if isinstance(adjudication, Mapping)
                else {}
            )
            conflict_unresolved = (
                isinstance(seam_adjudication, Mapping)
                and seam_adjudication.get("status")
                == "oracle_conflict_unresolved"
            )
            exclusions.append(
                comparative.make_exclusion(
                    study_id=str(manifest["study_id"]),
                    case_id=case_id,
                    decision_id=decision_id,
                    reason_code=(
                        "oracle_conflict_unresolved"
                        if conflict_unresolved
                        else "oracle_missing"
                    ),
                    stage="oracle-join",
                    detail=(
                        "explicitly unresolved under frozen oracle adjudication protocol"
                        if conflict_unresolved
                        else None
                    ),
                )
            )
            continue
        outcomes.append(
            comparative.make_outcome(
                str(observation["observation_id"]),
                "static-oracle",
                {"oracle": labels[decision_id]},
            )
        )

    report = comparative.build_decision_study_report(
        observations,
        outcomes,
        study_id=str(manifest["study_id"]),
        study_version=str(manifest["study_version"]),
        requests=requests,
        exclusions=exclusions,
        cohort=dict(manifest["identity"]),
        ece_minimum_n=int(spec["sample_policy"]["ece_minimum_n"]),
        minimum_oracle_n=int(spec["sample_policy"]["minimum_oracle_eligible_per_seam"]),
    )
    required_features = _required_features(spec)
    observed_features = set(report["seams"])
    report["eligibility"]["required_features_present"] = observed_features == required_features
    report["eligibility"]["study_eligible"] = (
        report["eligibility"]["all_observed_seams_eligible"]
        and observed_features == required_features
    )
    comparative.validate_record(report, comparative.DECISION_STUDY_REPORT_SCHEMA)

    _write_jsonl(run / _OUTCOMES, outcomes)
    _write_jsonl(run / _EXCLUSIONS, exclusions)
    atomic_write_json(run / _REPORT, report)
    atomic_write_bytes(
        run / _REPORT_MD,
        _render_report(report, oracle_version=str(oracle["oracle_version"])).encode("utf-8"),
    )
    return {
        "run": str(run),
        "report": str(run / _REPORT),
        "markdown": str(run / _REPORT_MD),
        "study_eligible": bool(report["eligibility"]["study_eligible"]),
        "oracle_version": oracle["oracle_version"],
        "oracle_sha256": sha256_file(Path(oracle_path)),
        "outcomes": len(outcomes),
        "exclusions": len(exclusions),
    }


def _public_oracle_projection(oracle: Mapping[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for raw in oracle.get("records", []):
        if not isinstance(raw, Mapping):
            raise WorkflowError("oracle record must be an object")
        provenance = raw.get("provenance", {})
        public_provenance: dict[str, Any] = {}
        if isinstance(provenance, Mapping):
            for key in ("protocol_version", "authoring_view_sha256", "frozen_at"):
                if key in provenance:
                    public_provenance[key] = provenance[key]
        public_provenance["public_projection"] = (
            "labels plus resolution status/method only; adjudicator identities, "
            "individual votes, pass hashes, discussion rationale, and participants removed"
        )

        adjudication: dict[str, Any] = {}
        raw_adjudication = raw.get("adjudication", {})
        if isinstance(raw_adjudication, Mapping):
            for decision_id, detail in raw_adjudication.items():
                if not isinstance(detail, Mapping):
                    continue
                adjudication[str(decision_id)] = {
                    key: detail[key]
                    for key in ("status", "method")
                    if key in detail
                }

        record = {
            "schema": comparative.DECISION_STUDY_ORACLE_SCHEMA,
            "case_id": raw["case_id"],
            "dataset_version": raw["dataset_version"],
            "labels": dict(raw.get("labels", {})),
            "provenance": public_provenance,
            "adjudication": adjudication,
            "frozen": True,
        }
        comparative.validate_record(record, comparative.DECISION_STUDY_ORACLE_SCHEMA)
        records.append(record)

    projected = {
        "schema": comparative.DECISION_STUDY_ORACLE_BUNDLE_SCHEMA,
        "study_id": oracle["study_id"],
        "dataset_version": oracle["dataset_version"],
        "oracle_version": oracle["oracle_version"],
        "frozen": True,
        "records": records,
    }
    comparative.validate_decision_study_oracle_bundle(
        projected,
        expected_study_id=str(oracle["study_id"]),
        expected_dataset_version=str(oracle["dataset_version"]),
    )
    return projected


def _walk_json_keys(value: Any, *, path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            current = f"{path}.{key}"
            found.append((current, str(key)))
            found.extend(_walk_json_keys(item, path=current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_json_keys(item, path=f"{path}[{index}]"))
    return found


def _verify_publication_privacy(destination: Path) -> dict[str, Any]:
    destination = Path(destination)
    expected_files = {
        "README.md",
        "study-spec.json",
        "datasets/corpus.json",
        "datasets/oracle.json",
        "metrics/decision-study-report.json",
        "analysis/decision-study-report.md",
        "evidence/run-manifest.json",
        "evidence/observations.jsonl",
        "evidence/provider-requests.jsonl",
        "evidence/exclusions.jsonl",
        "evidence/outcomes.jsonl",
    }
    actual_files = {
        item.relative_to(destination).as_posix()
        for item in destination.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise WorkflowError(
            "publication file set mismatch; "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )

    for item in destination.rglob("*"):
        if item.is_symlink():
            raise WorkflowError(
                f"refusing publication symlink: {item.relative_to(destination)}"
            )

    forbidden_keys = {
        "reasoning_summary",
        "reasoning_summaries",
        "redacted_reasoning",
        "participants",
        "rationale",
        "adjudicators",
        "pass_sha256",
        "pass_completed_at",
        "c_dispute_view_sha256",
        "resolutions_sha256",
    }
    host_markers = ("/home/", "/Users/", "/lump/", "C:\\Users\\")
    secret = os.environ.get("TYPESAFE_API_KEY")
    secret_bytes = secret.encode("utf-8") if secret else None

    for item in destination.rglob("*"):
        if not item.is_file():
            continue
        raw = item.read_bytes()
        relative = item.relative_to(destination).as_posix()
        if secret_bytes and secret_bytes in raw:
            raise WorkflowError(
                f"refusing publication: TYPESAFE_API_KEY appears in {relative}"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkflowError(
                f"refusing non-text publication artifact: {relative}"
            ) from exc
        for marker in host_markers:
            if marker in text:
                raise WorkflowError(
                    f"refusing publication: host-local path marker {marker!r} appears in {relative}"
                )

        if item.suffix == ".json":
            values = [json.loads(text)]
        elif item.suffix == ".jsonl":
            values = [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]
        else:
            values = []

        for value in values:
            for key_path, key in _walk_json_keys(value):
                if key.strip().lower() in forbidden_keys:
                    raise WorkflowError(
                        f"refusing publication: private key {key!r} at {relative}:{key_path}"
                    )

    observations = _jsonl(destination / "evidence/observations.jsonl")
    for observation in observations:
        privacy = observation.get("privacy", {})
        input_value = observation.get("input", {})
        if (
            not isinstance(privacy, Mapping)
            or privacy.get("raw_content_stored") is not False
            or privacy.get("secret_values_stored") is not False
            or not isinstance(input_value, Mapping)
            or input_value.get("raw_input_persisted") is not False
        ):
            raise WorkflowError("publication observation violates privacy contract")

    requests = _jsonl(destination / "evidence/provider-requests.jsonl")
    for request in requests:
        privacy = request.get("privacy", {})
        if (
            not isinstance(privacy, Mapping)
            or privacy.get("raw_content_stored") is not False
            or privacy.get("secret_values_stored") is not False
        ):
            raise WorkflowError("publication provider-request violates privacy contract")

    public_oracle = comparative.validate_decision_study_oracle_bundle(
        _read_json_object(destination / "datasets/oracle.json")
    )
    for record in public_oracle["records"]:
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping) or "public_projection" not in provenance:
            raise WorkflowError("publication oracle is not the public projection")
        adjudication = record.get("adjudication", {})
        if isinstance(adjudication, Mapping):
            for detail in adjudication.values():
                if isinstance(detail, Mapping) and (
                    set(detail) - {"status", "method"}
                ):
                    raise WorkflowError(
                        "publication oracle contains private adjudication detail"
                    )

    return {
        "exact_file_allowlist": True,
        "no_symlinks": True,
        "no_host_local_paths": True,
        "no_private_adjudication_keys": True,
        "observation_privacy_flags": True,
        "provider_request_privacy_flags": True,
        "oracle_public_projection": True,
        "typesafe_api_key_scan": bool(secret),
    }


def prepare_decision_study_publication(
    run: Path,
    oracle_path: Path,
    destination: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    report_result = report_decision_study(run, oracle_path)
    run = Path(run).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        if not force:
            raise WorkflowError(f"publication destination already exists: {destination}")
        if destination.is_symlink() or not destination.is_dir():
            raise WorkflowError(f"refusing to replace publication destination: {destination}")
        shutil.rmtree(destination)

    corpus = comparative.validate_decision_study_corpus(_read_json_object(run / _CORPUS))
    manifest = read_contract(run / _RUN, RUN_SCHEMA)
    oracle = comparative.validate_decision_study_oracle_bundle(
        _read_json_object(Path(oracle_path)),
        expected_study_id=str(manifest["study_id"]),
        expected_dataset_version=str(corpus["dataset_version"]),
    )
    report = json.loads((run / _REPORT).read_text(encoding="utf-8"))

    paths = {
        "study-spec.json": run / _STUDY_SPEC,
        "datasets/corpus.json": run / _CORPUS,
        "metrics/decision-study-report.json": run / _REPORT,
        "analysis/decision-study-report.md": run / _REPORT_MD,
        "evidence/run-manifest.json": run / _RUN,
        "evidence/observations.jsonl": run / _OBSERVATIONS,
        "evidence/provider-requests.jsonl": run / _REQUESTS,
        "evidence/exclusions.jsonl": run / _EXCLUSIONS,
        "evidence/outcomes.jsonl": run / _OUTCOMES,
    }
    for relative, source in paths.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    public_oracle = _public_oracle_projection(oracle)
    oracle_target = destination / "datasets/oracle.json"
    oracle_target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(oracle_target, public_oracle)

    status = (
        "eligible full-study evidence"
        if report_result["study_eligible"]
        else "development evidence; sample threshold not met"
    )
    readme = f"""# Routing Semantic Comparative Study

**Status:** {status}

This directory was produced by the benchmark decision-study publication pipeline. The inference corpus was executed before the separate frozen oracle was loaded. Raw TypeSafe HTTP request/response logs and private Inspect reasoning-summary artifacts are not part of this public tree.

The published oracle is a privacy-preserving projection: final frozen labels plus per-seam resolution status/method are retained, while adjudicator identities, individual A/B/C votes, pass hashes, recorded-discussion rationale, and participant identities are removed.

~~~mermaid
flowchart LR
    A[Inference corpus] --> B[Deterministic control]
    A --> C[One batched TypeSafe/Jev request per case]
    C --> D[Three per-seam observations]
    C --> E[One request-level efficiency record]
    F[Separate frozen oracle] --> G[Post-inference join]
    D --> G
    G --> H[Correctness / calibration / disagreement]
    E --> I[Latency / usage]
    H --> J[Decision-study report]
    I --> J
~~~

The report does not treat deterministic/semantic agreement as correctness. Correctness is derived only from the frozen oracle, and request-level efficiency is deduplicated by provider request ID.
"""
    atomic_write_bytes(destination / "README.md", readme.encode("utf-8"))

    privacy_checks = _verify_publication_privacy(destination)

    inventory = file_inventory(destination)
    publication = {
        "schema": PUBLICATION_SCHEMA,
        "study_id": manifest["study_id"],
        "study_version": manifest["study_version"],
        "dataset_version": corpus["dataset_version"],
        "oracle_version": oracle["oracle_version"],
        "prepared_at": _utc(),
        "study_eligible": bool(report_result["study_eligible"]),
        "files": {item["path"]: item["sha256"] for item in inventory},
        "limitations": list(report["limitations"]),
        "privacy": {
            "oracle_projection": "public-labels-resolution-method/v1",
            "raw_provider_http_included": False,
            "reasoning_summaries_included": False,
            "private_adjudicator_votes_included": False,
            "human_resolution_rationale_included": False,
            "human_participant_identity_included": False,
            "checks": privacy_checks,
        },
    }
    validate_instance(
        publication, PUBLICATION_SCHEMA, artifact="decision-study publication manifest"
    )
    atomic_write_json(destination / "publication.json", publication)
    write_manifest(destination)
    return {
        "destination": str(destination),
        "study_id": manifest["study_id"],
        "study_eligible": bool(report_result["study_eligible"]),
        "files": len(file_inventory(destination)),
        "manifest": str(destination / "publication.json"),
    }
