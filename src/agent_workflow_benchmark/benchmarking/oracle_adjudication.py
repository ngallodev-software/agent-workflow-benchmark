from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import agent_workflow_comparative_eval as comparative
from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .schema_contracts import validate_instance

ADJUDICATION_PASS_SCHEMA = "agent-workflow-benchmark/decision-study-adjudication-pass/v1"
DISPUTE_VIEW_SCHEMA = "agent-workflow-benchmark/decision-study-oracle-dispute-view/v1"
RESOLUTIONS_SCHEMA = "agent-workflow-benchmark/decision-study-adjudication-resolutions/v1"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid adjudication contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"adjudication contract must be an object: {path}")
    return value


def _study_spec(study: str) -> dict[str, Any]:
    try:
        return comparative.load_study_spec(study)
    except (ValueError, comparative.ContractError) as exc:
        raise WorkflowError(f"unknown or invalid decision study {study!r}: {exc}") from exc


def _decision_specs(spec: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["decision_id"]): item
        for item in spec["decision_seams"]
        if isinstance(item, Mapping)
    }


def _validate_label(
    decision_id: str,
    value: Any,
    *,
    decisions: Mapping[str, Mapping[str, Any]],
) -> None:
    seam = decisions.get(decision_id)
    if seam is None:
        raise WorkflowError(f"unknown decision seam in adjudication pass: {decision_id}")
    oracle_type = str(seam.get("oracle_type") or "")
    if oracle_type == "categorical":
        allowed = tuple(seam.get("labels") or ())
        if value not in allowed:
            raise WorkflowError(
                f"invalid label for {decision_id}: {value!r}; expected one of {allowed}"
            )
        return
    if oracle_type == "boolean":
        if not isinstance(value, bool):
            raise WorkflowError(f"invalid boolean label for {decision_id}: {value!r}")
        return
    if oracle_type == "ordinal":
        allowed = tuple(seam.get("levels") or ())
        if isinstance(value, bool) or value not in allowed:
            raise WorkflowError(
                f"invalid ordinal label for {decision_id}: {value!r}; expected one of {allowed}"
            )
        return
    raise WorkflowError(f"unsupported oracle_type for {decision_id}: {oracle_type!r}")


def _expected_from_authoring_view(view: Mapping[str, Any]) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for raw in view["cases"]:
        case_id = str(raw["case_id"])
        eligible = raw.get("oracle_eligible", {})
        if not isinstance(eligible, Mapping):
            raise WorkflowError(
                f"oracle-authoring case {case_id} has invalid oracle_eligible map"
            )
        expected[case_id] = {
            str(decision_id)
            for decision_id, enabled in eligible.items()
            if enabled is True
        }
    return expected


def _expected_from_dispute_view(view: Mapping[str, Any]) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for raw in view["cases"]:
        case_id = str(raw["case_id"])
        disputed = raw.get("disputed_decision_ids", [])
        if not isinstance(disputed, list):
            raise WorkflowError(
                f"oracle-dispute case {case_id} has invalid disputed_decision_ids"
            )
        expected[case_id] = {str(item) for item in disputed}
    return expected


def _load_view(
    path: Path,
    *,
    study: str,
) -> tuple[dict[str, Any], dict[str, set[str]], str]:
    path = Path(path)
    value = _read_json_object(path)
    schema = value.get("schema")
    spec = _study_spec(study)
    if schema == comparative.ORACLE_AUTHORING_VIEW_SCHEMA:
        try:
            comparative.validate_record(value, comparative.ORACLE_AUTHORING_VIEW_SCHEMA)
        except comparative.ContractError as exc:
            raise WorkflowError(f"invalid oracle-authoring view {path}: {exc}") from exc
        expected = _expected_from_authoring_view(value)
    elif schema == DISPUTE_VIEW_SCHEMA:
        validate_instance(value, DISPUTE_VIEW_SCHEMA, artifact=str(path))
        expected = _expected_from_dispute_view(value)
    else:
        raise WorkflowError(
            f"unsupported adjudication view schema {schema!r}; expected "
            f"{comparative.ORACLE_AUTHORING_VIEW_SCHEMA!r} or {DISPUTE_VIEW_SCHEMA!r}"
        )
    if value.get("study_id") != spec["study_id"]:
        raise WorkflowError(
            f"adjudication view study_id {value.get('study_id')!r} does not match "
            f"{spec['study_id']!r}"
        )
    return value, expected, sha256_file(path)


def _load_adjudication_pass(
    view_path: Path,
    pass_path: Path,
    *,
    study: str,
) -> dict[str, Any]:
    view, expected, view_sha256 = _load_view(view_path, study=study)
    spec = _study_spec(study)
    decisions = _decision_specs(spec)
    value = _read_json_object(pass_path)
    validate_instance(value, ADJUDICATION_PASS_SCHEMA, artifact=str(pass_path))

    if value["study_id"] != view["study_id"]:
        raise WorkflowError("adjudication pass belongs to a different study")
    if value["dataset_version"] != view["dataset_version"]:
        raise WorkflowError("adjudication pass dataset_version does not match its view")
    if value["protocol_version"] != spec["oracle_policy"]["protocol_version"]:
        raise WorkflowError("adjudication pass protocol_version is not frozen study protocol")
    if value["input_view_sha256"] != view_sha256:
        raise WorkflowError("adjudication pass input_view_sha256 does not match supplied view")

    records_by_case: dict[str, Mapping[str, Any]] = {}
    for raw in value["records"]:
        case_id = str(raw["case_id"])
        if case_id in records_by_case:
            raise WorkflowError(f"duplicate adjudication case ID: {case_id}")
        if case_id not in expected:
            raise WorkflowError(f"adjudication pass contains unknown case ID: {case_id}")
        labels = raw.get("labels")
        if not isinstance(labels, Mapping):
            raise WorkflowError(f"adjudication labels for {case_id} must be an object")
        actual = {str(item) for item in labels}
        wanted = expected[case_id]
        if actual != wanted:
            missing = sorted(wanted - actual)
            extra = sorted(actual - wanted)
            raise WorkflowError(
                f"adjudication labels for {case_id} do not match required seams; "
                f"missing={missing}, extra={extra}"
            )
        for decision_id, label in labels.items():
            _validate_label(str(decision_id), label, decisions=decisions)
        records_by_case[case_id] = raw

    if set(records_by_case) != set(expected):
        missing_cases = sorted(set(expected) - set(records_by_case))
        extra_cases = sorted(set(records_by_case) - set(expected))
        raise WorkflowError(
            "adjudication pass case set does not match supplied view; "
            f"missing={missing_cases}, extra={extra_cases}"
        )

    return {
        "view": view,
        "view_sha256": view_sha256,
        "contract": value,
        "adjudicator_id": value["adjudicator_id"],
        "pass_sha256": sha256_file(Path(pass_path)),
        "records_by_case": records_by_case,
        "labels": sum(len(raw["labels"]) for raw in records_by_case.values()),
    }


def validate_adjudication_pass(
    view_path: Path,
    pass_path: Path,
    *,
    study: str = "routing-semantic-v1",
) -> dict[str, Any]:
    loaded = _load_adjudication_pass(view_path, pass_path, study=study)
    value = loaded["contract"]
    return {
        "valid": True,
        "study_id": value["study_id"],
        "dataset_version": value["dataset_version"],
        "protocol_version": value["protocol_version"],
        "adjudicator_id": loaded["adjudicator_id"],
        "input_view_sha256": loaded["view_sha256"],
        "pass_sha256": loaded["pass_sha256"],
        "cases": len(loaded["records_by_case"]),
        "labels": loaded["labels"],
    }


def _assert_independent_ids(a: Mapping[str, Any], b: Mapping[str, Any]) -> None:
    if str(a["adjudicator_id"]) == str(b["adjudicator_id"]):
        raise WorkflowError("A and B adjudication passes must use distinct adjudicator_id values")


def _disputes(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, set[str]]:
    disputes: dict[str, set[str]] = {}
    a_records = a["records_by_case"]
    b_records = b["records_by_case"]
    for case_id in sorted(a_records):
        a_labels = a_records[case_id]["labels"]
        b_labels = b_records[case_id]["labels"]
        for decision_id in sorted(a_labels):
            if a_labels[decision_id] != b_labels[decision_id]:
                disputes.setdefault(case_id, set()).add(decision_id)
    return disputes


def export_oracle_dispute_view(
    authoring_view_path: Path,
    pass_a_path: Path,
    pass_b_path: Path,
    destination: Path,
    *,
    study: str = "routing-semantic-v1",
    force: bool = False,
) -> dict[str, Any]:
    authoring_view, _, authoring_sha256 = _load_view(
        authoring_view_path, study=study
    )
    if authoring_view["schema"] != comparative.ORACLE_AUTHORING_VIEW_SCHEMA:
        raise WorkflowError("A/B dispute detection requires the canonical oracle-authoring view")
    a = _load_adjudication_pass(authoring_view_path, pass_a_path, study=study)
    b = _load_adjudication_pass(authoring_view_path, pass_b_path, study=study)
    _assert_independent_ids(a, b)
    disputes = _disputes(a, b)

    by_case = {str(case["case_id"]): case for case in authoring_view["cases"]}
    cases: list[dict[str, Any]] = []
    decision_ids: set[str] = set()
    for case_id in sorted(disputes):
        source = by_case[case_id]
        ids = sorted(disputes[case_id])
        decision_ids.update(ids)
        cases.append(
            {
                "case_id": case_id,
                "task": source["task"],
                "metadata": dict(source["metadata"]),
                "oracle_eligible": dict(source["oracle_eligible"]),
                "disputed_decision_ids": ids,
            }
        )

    decision_seams = [
        item
        for item in authoring_view["decision_seams"]
        if str(item.get("decision_id")) in decision_ids
    ]
    record = {
        "schema": DISPUTE_VIEW_SCHEMA,
        "study_id": authoring_view["study_id"],
        "dataset_version": authoring_view["dataset_version"],
        "protocol_version": _study_spec(study)["oracle_policy"]["protocol_version"],
        "source_authoring_view_sha256": authoring_sha256,
        "decision_seams": decision_seams,
        "oracle_policy": dict(authoring_view["oracle_policy"]),
        "cases": cases,
        "blinding": {
            "construction_tags_included": False,
            "control_outputs_included": False,
            "candidate_outputs_included": False,
            "a_b_labels_included": False,
        },
    }
    validate_instance(record, DISPUTE_VIEW_SCHEMA, artifact="oracle dispute view")

    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"oracle dispute view already exists: {destination}")
    if destination.exists() and (destination.is_dir() or destination.is_symlink()):
        raise WorkflowError(f"oracle dispute view must be a regular file path: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        "study_id": record["study_id"],
        "dataset_version": record["dataset_version"],
        "disputed_cases": len(cases),
        "disputed_seams": sum(len(item["disputed_decision_ids"]) for item in cases),
        "requires_c": bool(cases),
    }


def _load_resolutions(
    path: Path | None,
    *,
    authoring_view: Mapping[str, Any],
    authoring_view_sha256: str,
    study: str,
    decisions: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None:
        return {}
    value = _read_json_object(path)
    validate_instance(value, RESOLUTIONS_SCHEMA, artifact=str(path))
    spec = _study_spec(study)
    if value["study_id"] != authoring_view["study_id"]:
        raise WorkflowError("adjudication resolutions belong to a different study")
    if value["dataset_version"] != authoring_view["dataset_version"]:
        raise WorkflowError("adjudication resolutions dataset_version mismatch")
    if value["protocol_version"] != spec["oracle_policy"]["protocol_version"]:
        raise WorkflowError("adjudication resolutions protocol_version mismatch")
    if value["authoring_view_sha256"] != authoring_view_sha256:
        raise WorkflowError("adjudication resolutions authoring_view_sha256 mismatch")

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in value["records"]:
        case_id = str(raw["case_id"])
        decision_id = str(raw["decision_id"])
        key = (case_id, decision_id)
        if key in result:
            raise WorkflowError(
                f"duplicate adjudication resolution for {case_id}:{decision_id}"
            )
        if raw["status"] == "resolved":
            if "label" not in raw:
                raise WorkflowError(
                    f"resolved adjudication entry lacks label for {case_id}:{decision_id}"
                )
            _validate_label(decision_id, raw["label"], decisions=decisions)
        elif "label" in raw and raw["label"] is not None:
            raise WorkflowError(
                f"unresolved adjudication entry must not contain a label for "
                f"{case_id}:{decision_id}"
            )
        result[key] = dict(raw)
    return result


def freeze_oracle_bundle(
    authoring_view_path: Path,
    pass_a_path: Path,
    pass_b_path: Path,
    destination: Path,
    *,
    oracle_version: str,
    c_view_path: Path | None = None,
    pass_c_path: Path | None = None,
    resolutions_path: Path | None = None,
    study: str = "routing-semantic-v1",
    force: bool = False,
) -> dict[str, Any]:
    authoring_view, expected, authoring_sha256 = _load_view(
        authoring_view_path, study=study
    )
    if authoring_view["schema"] != comparative.ORACLE_AUTHORING_VIEW_SCHEMA:
        raise WorkflowError("oracle freeze requires the canonical oracle-authoring view")
    spec = _study_spec(study)
    decisions = _decision_specs(spec)
    a = _load_adjudication_pass(authoring_view_path, pass_a_path, study=study)
    b = _load_adjudication_pass(authoring_view_path, pass_b_path, study=study)
    _assert_independent_ids(a, b)
    disputes = _disputes(a, b)

    c: dict[str, Any] | None = None
    if disputes:
        if c_view_path is None or pass_c_path is None:
            raise WorkflowError(
                f"{sum(len(items) for items in disputes.values())} A/B disagreements require "
                "both the blinded C dispute view and an independent C pass before oracle freeze"
            )
        c_view, c_expected, _ = _load_view(c_view_path, study=study)
        if c_view["schema"] != DISPUTE_VIEW_SCHEMA:
            raise WorkflowError("C pass must be validated against an oracle dispute view")
        if c_view["source_authoring_view_sha256"] != authoring_sha256:
            raise WorkflowError("C dispute view was not derived from this authoring view")
        if c_expected != disputes:
            raise WorkflowError(
                "C dispute view seam set does not match current A/B disagreements"
            )
        c = _load_adjudication_pass(c_view_path, pass_c_path, study=study)
        if str(c["adjudicator_id"]) in {
            str(a["adjudicator_id"]),
            str(b["adjudicator_id"]),
        }:
            raise WorkflowError("C adjudicator_id must differ from both A and B")
    elif c_view_path is not None or pass_c_path is not None:
        raise WorkflowError("C adjudication inputs were supplied but A/B have no disagreements")

    resolutions = _load_resolutions(
        resolutions_path,
        authoring_view=authoring_view,
        authoring_view_sha256=authoring_sha256,
        study=study,
        decisions=decisions,
    )

    a_records = a["records_by_case"]
    b_records = b["records_by_case"]
    c_records = c["records_by_case"] if c is not None else {}
    three_way_conflicts: set[tuple[str, str]] = set()
    if c is not None:
        for case_id, decision_ids in disputes.items():
            for decision_id in decision_ids:
                votes = [
                    a_records[case_id]["labels"][decision_id],
                    b_records[case_id]["labels"][decision_id],
                    c_records[case_id]["labels"][decision_id],
                ]
                if not any(votes.count(item) >= 2 for item in votes):
                    three_way_conflicts.add((case_id, decision_id))
    for key in resolutions:
        if key not in three_way_conflicts:
            raise WorkflowError(
                "adjudication resolution is only valid for a three-way conflict: "
                f"{key[0]}:{key[1]}"
            )

    frozen_at = _utc()
    oracle_records: list[dict[str, Any]] = []
    unresolved = 0
    majority_resolved = 0
    discussion_resolved = 0
    direct_agreements = 0

    for case_id in sorted(expected):
        labels: dict[str, Any] = {}
        adjudication: dict[str, Any] = {}
        for decision_id in sorted(expected[case_id]):
            a_label = a_records[case_id]["labels"][decision_id]
            b_label = b_records[case_id]["labels"][decision_id]
            if a_label == b_label:
                labels[decision_id] = a_label
                direct_agreements += 1
                adjudication[decision_id] = {
                    "status": "resolved",
                    "method": "a_b_agreement",
                    "a": a_label,
                    "b": b_label,
                }
                continue

            if c is None:
                raise WorkflowError("internal error: disagreement reached freeze without C pass")
            c_label = c_records[case_id]["labels"][decision_id]
            votes = [a_label, b_label, c_label]
            majority = next((item for item in votes if votes.count(item) >= 2), None)
            if majority is not None:
                labels[decision_id] = majority
                majority_resolved += 1
                adjudication[decision_id] = {
                    "status": "resolved",
                    "method": "two_of_three_majority",
                    "a": a_label,
                    "b": b_label,
                    "c": c_label,
                }
                continue

            resolution = resolutions.get((case_id, decision_id))
            if resolution is None:
                raise WorkflowError(
                    "three-way conflict requires recorded adjudication resolution: "
                    f"{case_id}:{decision_id}"
                )
            if resolution["status"] == "resolved":
                labels[decision_id] = resolution["label"]
                discussion_resolved += 1
                adjudication[decision_id] = {
                    "status": "resolved",
                    "method": "recorded_discussion",
                    "a": a_label,
                    "b": b_label,
                    "c": c_label,
                    "rationale": resolution["rationale"],
                    "participants": list(resolution.get("participants") or []),
                }
            else:
                unresolved += 1
                adjudication[decision_id] = {
                    "status": "oracle_conflict_unresolved",
                    "method": "recorded_discussion",
                    "a": a_label,
                    "b": b_label,
                    "c": c_label,
                    "rationale": resolution["rationale"],
                    "participants": list(resolution.get("participants") or []),
                }

        record = {
            "schema": comparative.DECISION_STUDY_ORACLE_SCHEMA,
            "case_id": case_id,
            "dataset_version": authoring_view["dataset_version"],
            "labels": labels,
            "provenance": {
                "protocol_version": spec["oracle_policy"]["protocol_version"],
                "authoring_view_sha256": authoring_sha256,
                "adjudicators": {
                    "a": a["adjudicator_id"],
                    "b": b["adjudicator_id"],
                    **({"c": c["adjudicator_id"]} if c is not None else {}),
                },
                "pass_sha256": {
                    "a": a["pass_sha256"],
                    "b": b["pass_sha256"],
                    **({"c": c["pass_sha256"]} if c is not None else {}),
                },
                "frozen_at": frozen_at,
            },
            "adjudication": adjudication,
            "frozen": True,
        }
        comparative.validate_record(record, comparative.DECISION_STUDY_ORACLE_SCHEMA)
        oracle_records.append(record)

    bundle = {
        "schema": comparative.DECISION_STUDY_ORACLE_BUNDLE_SCHEMA,
        "study_id": authoring_view["study_id"],
        "dataset_version": authoring_view["dataset_version"],
        "oracle_version": oracle_version,
        "frozen": True,
        "records": oracle_records,
    }
    try:
        comparative.validate_decision_study_oracle_bundle(
            bundle,
            expected_study_id=str(authoring_view["study_id"]),
            expected_dataset_version=str(authoring_view["dataset_version"]),
        )
    except (ValueError, comparative.ContractError) as exc:
        raise WorkflowError(f"assembled oracle bundle is invalid: {exc}") from exc

    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"frozen oracle destination already exists: {destination}")
    if destination.exists() and (destination.is_dir() or destination.is_symlink()):
        raise WorkflowError(f"frozen oracle destination must be a regular file path: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, bundle)

    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        "study_id": bundle["study_id"],
        "dataset_version": bundle["dataset_version"],
        "oracle_version": bundle["oracle_version"],
        "records": len(oracle_records),
        "labels": sum(len(record["labels"]) for record in oracle_records),
        "direct_agreements": direct_agreements,
        "majority_resolved": majority_resolved,
        "discussion_resolved": discussion_resolved,
        "unresolved": unresolved,
        "frozen": True,
    }
