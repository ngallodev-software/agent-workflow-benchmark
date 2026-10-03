from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file
from agent_workflow_comparative_eval import (
    build_paired_decision_report,
    validate_paired_decision_trial,
)

from .agentic_jev_swe_manager_v2_study import (
    RUN_SCHEMA,
    STUDY_ID,
    STUDY_VERSION,
    TARGET_TASKS,
)
from .schema_contracts import validate_instance

PUBLICATION_SCHEMA = (
    "agent-workflow-benchmark/agentic-jev-swe-manager-publication/v2"
)

_PUBLIC_FILES = (
    "README.md",
    "publication.json",
    "metrics/paired-report.json",
    "evidence/paired-trials.jsonl",
    "evidence/private-artifact-hashes.json",
)
_USER_PATH_PATTERNS = (
    re.compile(r"/home/[^/\s]+/"),
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"expected JSON object: {path}")
    return value


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _canonical_line(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_codex_identity(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = ("policy", "requested", "resolved", "platform")
    return {key: value[key] for key in allowed if key in value}


def _safe_runtime(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowError("run runtime must be an object")
    required = (
        "model",
        "reasoning_effort",
        "skill_commit",
        "skill_sha256",
        "codex_version",
        "benchmark_source",
        "package_versions",
        "dependency_code_sha256",
    )
    missing = [key for key in required if key not in value]
    if missing:
        raise WorkflowError(
            "run runtime is missing publication identity fields: "
            + ", ".join(sorted(missing))
        )
    result: dict[str, Any] = {
        "model": value["model"],
        "reasoning_effort": value["reasoning_effort"],
        "skill_commit": value["skill_commit"],
        "skill_sha256": value["skill_sha256"],
        "skill_interface_sha256": value.get("skill_interface_sha256"),
        "manager_policy_id": value.get("manager_policy_id"),
        "manager_policy_version": value.get("manager_policy_version"),
        "request_builder_version": value.get("request_builder_version"),
        "codex_version": value["codex_version"],
        "requested_jev_model": value.get(
            "requested_jev_model", value.get("jev_model")
        ),
        "benchmark_source": dict(value["benchmark_source"])
        if isinstance(value["benchmark_source"], Mapping)
        else value["benchmark_source"],
        "package_versions": dict(value["package_versions"])
        if isinstance(value["package_versions"], Mapping)
        else value["package_versions"],
        "dependency_code_sha256": dict(value["dependency_code_sha256"])
        if isinstance(value["dependency_code_sha256"], Mapping)
        else value["dependency_code_sha256"],
        "model_args": (
            {"responses_api": value["model_args"].get("responses_api")}
            if isinstance(value.get("model_args"), Mapping)
            and "responses_api" in value["model_args"]
            else {}
        ),
        "codex_cli": _safe_codex_identity(value.get("codex_cli")),
    }
    return result


def _trial_paths(run_root: Path, run: Mapping[str, Any]) -> list[tuple[str, Path]]:
    execution = run.get("execution")
    if not isinstance(execution, Mapping):
        raise WorkflowError("run execution must be an object")
    samples = execution.get("samples")
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise WorkflowError("run execution samples must be an array")
    result: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for item in samples:
        if not isinstance(item, Mapping):
            raise WorkflowError("run execution sample entry must be an object")
        sample_id = item.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise WorkflowError("run execution sample has no sample_id")
        if sample_id in seen:
            raise WorkflowError(f"duplicate run sample id: {sample_id}")
        seen.add(sample_id)
        result.append(
            (
                sample_id,
                run_root / "samples" / sample_id / "paired-trial.json",
            )
        )
    return result


def _load_trials(
    run_root: Path,
    run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for sample_id, path in _trial_paths(run_root, run):
        if not path.is_file():
            raise WorkflowError(f"missing paired trial for sample {sample_id}: {path}")
        trial = _load_json_object(path)
        validate_paired_decision_trial(trial)
        if trial.get("study_id") != STUDY_ID:
            raise WorkflowError(f"paired trial belongs to another study: {sample_id}")
        if trial.get("sample_id") != sample_id:
            raise WorkflowError(
                f"paired trial sample identity mismatch: {sample_id}"
            )
        trials.append(trial)
    return trials


def _require_complete_run(
    run: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if run.get("study_id") != STUDY_ID or run.get("study_version") != STUDY_VERSION:
        raise WorkflowError("run is not the preregistered Agentic-Jev SWE manager study")
    validate_instance(run, RUN_SCHEMA, artifact="Agentic-Jev SWE manager run")

    execution = run.get("execution")
    if not isinstance(execution, Mapping):
        raise WorkflowError("run execution must be an object")
    expected = execution.get("paired_samples_expected")
    observed = execution.get("paired_samples_observed")
    if expected != observed or observed != len(trials) or observed != TARGET_TASKS:
        raise WorkflowError(
            "publication requires the complete preregistered 30-pair cohort"
        )
    if execution.get("official_scoring_enabled") is not True:
        raise WorkflowError("publication requires official SWE-Lancer scoring")
    if execution.get("outcome_read_after_both_arms") is not True:
        raise WorkflowError("publication requires the paired outcome-read barrier")

    evidence_policy = run.get("evidence_policy")
    if not isinstance(evidence_policy, Mapping):
        raise WorkflowError("run evidence policy must be an object")
    required_policy = {
        "inspect_logs_are_canonical_execution_evidence": True,
        "official_swe_lancer_score_is_canonical_correctness": True,
        "hidden_chain_of_thought_exported": False,
        "raw_jev_context_public": False,
        "raw_provider_http_public": False,
        "credentials_public": False,
    }
    for key, expected_value in required_policy.items():
        if evidence_policy.get(key) is not expected_value:
            raise WorkflowError(f"run evidence policy does not satisfy {key}")

    sample_entries = execution.get("samples")
    if not isinstance(sample_entries, Sequence) or isinstance(
        sample_entries, (str, bytes)
    ):
        raise WorkflowError("run execution samples must be an array")
    for item in sample_entries:
        if not isinstance(item, Mapping):
            raise WorkflowError("run execution sample entry must be an object")
        if item.get("control_api_key_absent") is not True:
            raise WorkflowError(
                f"control transcript credential check failed for {item.get('sample_id')}"
            )
        if item.get("treatment_api_key_absent") is not True:
            raise WorkflowError(
                f"treatment transcript credential check failed for {item.get('sample_id')}"
            )

    report = build_paired_decision_report(
        trials,
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        minimum_interval_n=10,
    )
    if report != run.get("report"):
        raise WorkflowError(
            "stored paired report does not reproduce exactly from paired trials"
        )
    return report


def _private_file_hash(
    path_value: object,
    *,
    label: str,
    fallback: Path | None = None,
) -> str:
    candidates: list[Path] = []
    if isinstance(path_value, str) and path_value:
        candidates.append(Path(path_value))
    if fallback is not None:
        candidates.append(Path(fallback))
    for path in candidates:
        if path.is_file():
            return sha256_file(path)
    raise WorkflowError(f"missing private evidence file for {label}")


def _inspect_log_hash(
    *,
    path_value: object,
    sample_root: Path,
    arm: str,
) -> str:
    if isinstance(path_value, str) and path_value:
        direct = Path(path_value)
        if direct.is_file():
            return sha256_file(direct)
    log_root = sample_root / arm / "inspect-logs"
    matches = sorted(path for path in log_root.rglob("*.eval") if path.is_file())
    if len(matches) != 1:
        raise WorkflowError(
            f"expected exactly one private Inspect log for {sample_root.name}/{arm}; "
            f"observed {len(matches)}"
        )
    return sha256_file(matches[0])


def _private_evidence_hashes(
    run_root: Path,
    run: Mapping[str, Any],
) -> dict[str, Any]:
    execution = run["execution"]
    samples = execution["samples"]
    records: list[dict[str, Any]] = []
    for item in samples:
        sample_id = str(item["sample_id"])
        treatment_receipts = (
            run_root
            / "samples"
            / sample_id
            / "treatment"
            / "jev-tool-receipts.jsonl"
        )
        treatment_history = (
            run_root
            / "samples"
            / sample_id
            / "treatment"
            / "jev-request-history-v2.jsonl"
        )
        sample_root = run_root / "samples" / sample_id
        record = {
            "sample_id": sample_id,
            "control_inspect_log_sha256": _inspect_log_hash(
                path_value=item.get("control_inspect_log"),
                sample_root=sample_root,
                arm="control",
            ),
            "treatment_inspect_log_sha256": _inspect_log_hash(
                path_value=item.get("treatment_inspect_log"),
                sample_root=sample_root,
                arm="treatment",
            ),
            "treatment_jev_receipts_sha256": (
                sha256_file(treatment_receipts)
                if treatment_receipts.is_file()
                else None
            ),
            "treatment_jev_request_history_sha256": (
                sha256_file(treatment_history)
                if treatment_history.is_file()
                else None
            ),
            "paired_trial_sha256": sha256_file(
                run_root / "samples" / sample_id / "paired-trial.json"
            ),
        }
        records.append(record)

    start_manifest = run.get("start_manifest")
    if not isinstance(start_manifest, Mapping):
        raise WorkflowError("run has no start_manifest")
    start_path = start_manifest.get("path")
    start_hash = _private_file_hash(
        start_path,
        label="run-start manifest",
        fallback=run_root / "run-start.json",
    )
    if start_hash != start_manifest.get("sha256"):
        raise WorkflowError("run-start manifest hash no longer matches run record")

    return {
        "schema": "agent-workflow-benchmark/agentic-jev-swe-manager-private-hashes/v1",
        "run_manifest_sha256": sha256_file(run_root / "run-manifest.json"),
        "run_start_sha256": start_hash,
        "raw_private_artifacts_published": False,
        "samples": records,
    }


def _source_projection(trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    source = trials[0].get("source")
    if not isinstance(source, Mapping):
        raise WorkflowError("paired trial source must be an object")
    return dict(source)


def _public_readme(publication: Mapping[str, Any]) -> str:
    return (
        "# Agentic-Jev SWE-Lancer manager v2 public evidence\n\n"
        "This tree is the sanitized publication projection for "
        "agentic-jev-swe-manager-v2. Official Inspect Evals SWE-Lancer "
        "scoring is the sole correctness authority. The primary estimate is "
        "treatment attempt accuracy minus control attempt accuracy across the "
        "complete frozen paired cohort.\n\n"
        "The bundle includes the paired report and public-safe paired trial "
        "records, including bounded visible decision evidence and Jev process "
        "aggregates. It does not include Inspect logs, raw Jev requests or "
        "responses, provider HTTP payloads, credentials, hidden chain-of-thought, "
        "or local user paths. Hashes of retained private execution evidence are "
        "published separately for provenance.\n\n"
        "Treatment tasks where the agent did not call Jev remain in the primary "
        "denominator. Called-only subsets are descriptive only. Semantic agreement "
        "with Jev is not correctness. Dollar cost is unavailable in v1 because no "
        "authoritative billing schedule was frozen before execution.\n\n"
        f"Paired tasks: {publication['paired_n']}\n"
        f"Cohort SHA-256: {publication['cohort_sha256']}\n"
    )


def _scan_public_tree(
    root: Path,
    *,
    private_root: Path | None = None,
) -> None:
    private_root_text = str(private_root.resolve()) if private_root is not None else ""
    secret = os.environ.get("TYPESAFE_API_KEY")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise WorkflowError(f"public bundle must not contain symlinks: {path}")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if secret and secret in text:
            raise WorkflowError(f"public bundle contains API key value: {path}")
        if private_root_text and private_root_text in text:
            raise WorkflowError(f"public bundle leaks private run-root path: {path}")
        for pattern in _USER_PATH_PATTERNS:
            if pattern.search(text):
                raise WorkflowError(f"public bundle contains local user path: {path}")


def _write_manifest(root: Path) -> None:
    lines: list[str] = []
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.name != "MANIFEST.sha256"
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}")
    _write_text(root / "MANIFEST.sha256", "\n".join(lines) + "\n")


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid JSONL at {path}:{number}: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkflowError(f"expected JSON object at {path}:{number}")
        result.append(value)
    return result


def _verify_manifest(root: Path) -> None:
    manifest_path = root / "MANIFEST.sha256"
    if not manifest_path.is_file():
        raise WorkflowError("public bundle has no MANIFEST.sha256")
    recorded: dict[str, str] = {}
    for number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line:
            continue
        digest, separator, relative = line.partition("  ")
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not relative
            or relative in recorded
        ):
            raise WorkflowError(f"invalid public manifest line {number}")
        recorded[relative] = digest
    actual = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if path.is_file() and path.name != "MANIFEST.sha256"
    }
    if recorded != actual:
        raise WorkflowError("public bundle manifest does not match file contents")


def verify_swe_manager_publication(root: Path) -> dict[str, Any]:
    root = Path(root)
    expected_files = set(_PUBLIC_FILES) | {"MANIFEST.sha256"}
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise WorkflowError(
            "public bundle differs from the exact file allowlist: "
            f"{sorted(actual_files)}"
        )
    if any(path.is_symlink() for path in root.rglob("*")):
        raise WorkflowError("public bundle must not contain symlinks")

    _verify_manifest(root)
    publication = _load_json_object(root / "publication.json")
    validate_instance(
        publication,
        PUBLICATION_SCHEMA,
        artifact="Agentic-Jev SWE manager v2 publication",
    )
    if publication.get("files") != list(_PUBLIC_FILES):
        raise WorkflowError("publication file declaration differs from allowlist")
    if publication.get("paired_n") != TARGET_TASKS:
        raise WorkflowError("publication does not contain the complete 30-pair cohort")

    trials = _read_jsonl_objects(root / "evidence" / "paired-trials.jsonl")
    if len(trials) != TARGET_TASKS:
        raise WorkflowError("public paired-trial count is not 30")
    sample_ids: set[str] = set()
    for trial in trials:
        validate_paired_decision_trial(trial)
        sample_id = str(trial.get("sample_id") or "")
        if not sample_id or sample_id in sample_ids:
            raise WorkflowError("public paired trials contain duplicate/empty sample IDs")
        sample_ids.add(sample_id)

    report = _load_json_object(root / "metrics" / "paired-report.json")
    rebuilt = build_paired_decision_report(
        trials,
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        minimum_interval_n=10,
    )
    if rebuilt != report:
        raise WorkflowError("public paired report does not reproduce from public trials")
    if report.get("cohort_sha256") != publication.get("cohort_sha256"):
        raise WorkflowError("publication cohort identity differs from paired report")
    if dict(trials[0]["source"]) != publication.get("source"):
        raise WorkflowError("publication source identity differs from paired trials")

    trial_runtime = trials[0]["runtime"]
    public_runtime = publication.get("runtime")
    if not isinstance(public_runtime, Mapping):
        raise WorkflowError("publication runtime must be an object")
    for key in (
        "model",
        "reasoning_effort",
        "skill_commit",
        "skill_sha256",
        "codex_version",
        "requested_jev_model",
        "benchmark_source",
        "package_versions",
        "dependency_code_sha256",
    ):
        if public_runtime.get(key) != trial_runtime.get(key):
            raise WorkflowError(
                f"publication runtime field differs from paired trials: {key}"
            )

    private_hashes = _load_json_object(
        root / "evidence" / "private-artifact-hashes.json"
    )
    if private_hashes.get("raw_private_artifacts_published") is not False:
        raise WorkflowError("private evidence projection must publish hashes only")
    private_samples = private_hashes.get("samples")
    if (
        not isinstance(private_samples, list)
        or len(private_samples) != TARGET_TASKS
        or {str(item.get("sample_id")) for item in private_samples} != sample_ids
    ):
        raise WorkflowError("private evidence hash projection is incomplete")
    for item in private_samples:
        for key in (
            "control_inspect_log_sha256",
            "treatment_inspect_log_sha256",
            "paired_trial_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(key) or "")):
                raise WorkflowError(f"invalid private evidence digest: {key}")
        receipt_hash = item.get("treatment_jev_receipts_sha256")
        if receipt_hash is not None and not re.fullmatch(
            r"[0-9a-f]{64}", str(receipt_hash)
        ):
            raise WorkflowError("invalid private Jev receipt digest")
        history_hash = item.get("treatment_jev_request_history_sha256")
        if history_hash is not None and not re.fullmatch(
            r"[0-9a-f]{64}", str(history_hash)
        ):
            raise WorkflowError("invalid private Jev request-history digest")

    _scan_public_tree(root)
    return {
        "status": "pass",
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "paired_n": len(trials),
        "cohort_sha256": report["cohort_sha256"],
        "manifest_sha256": sha256_file(root / "MANIFEST.sha256"),
    }


def prepare_swe_manager_publication(
    *,
    run_root: Path,
    destination: Path,
) -> dict[str, Any]:
    run_root = Path(run_root)
    destination = Path(destination)
    run_path = run_root / "run-manifest.json"
    if not run_path.is_file():
        raise WorkflowError(f"missing completed run manifest: {run_path}")
    if destination.exists():
        if any(destination.iterdir()):
            raise WorkflowError(
                "publication destination is not empty; review/preserve prior evidence"
            )
    else:
        destination.mkdir(parents=True)

    run = _load_json_object(run_path)
    trials = _load_trials(run_root, run)
    report = _require_complete_run(run, trials)
    source = _source_projection(trials)
    cohort_sha256 = str(report.get("cohort_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", cohort_sha256):
        raise WorkflowError("paired report has no valid cohort_sha256")

    runtime = _safe_runtime(run.get("runtime"))
    private_hashes = _private_evidence_hashes(run_root, run)
    first_arm_counts = Counter(
        str(item.get("first_arm"))
        for item in run["execution"]["samples"]
    )

    publication = {
        "schema": PUBLICATION_SCHEMA,
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "prepared_at": _utc(),
        "source_run_sha256": sha256_file(run_path),
        "cohort_sha256": cohort_sha256,
        "paired_n": len(trials),
        "source": source,
        "runtime": {
            **runtime,
            "first_arm_counts": dict(sorted(first_arm_counts.items())),
        },
        "claim_boundary": {
            "within_frozen_cohort_only": True,
            "called_only_subset_descriptive_only": True,
            "semantic_agreement_is_not_correctness": True,
            "dollar_cost_available": False,
        },
        "privacy": {
            "raw_provider_http_included": False,
            "raw_jev_context_included": False,
            "raw_jev_receipts_included": False,
            "inspect_logs_included": False,
            "credentials_included": False,
            "hidden_chain_of_thought_included": False,
            "local_user_paths_included": False,
            "visible_decision_evidence_included": True,
            "private_evidence_hashes_only": True,
        },
        "files": list(_PUBLIC_FILES),
    }
    validate_instance(
        publication,
        PUBLICATION_SCHEMA,
        artifact="Agentic-Jev SWE manager v2 publication",
    )

    atomic_write_json(destination / "publication.json", publication)
    atomic_write_json(destination / "metrics" / "paired-report.json", report)
    atomic_write_json(
        destination / "evidence" / "private-artifact-hashes.json",
        private_hashes,
    )
    _write_text(
        destination / "evidence" / "paired-trials.jsonl",
        "".join(_canonical_line(trial) + "\n" for trial in trials),
    )
    _write_text(destination / "README.md", _public_readme(publication))

    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual_files != set(_PUBLIC_FILES):
        raise WorkflowError(
            "publication tree differs from the public allowlist before manifest: "
            f"{sorted(actual_files)}"
        )
    _scan_public_tree(destination, private_root=run_root)
    _write_manifest(destination)
    verification = verify_swe_manager_publication(destination)

    return {
        "path": str(destination),
        "publication": publication,
        "verification": verification,
        "manifest_sha256": sha256_file(destination / "MANIFEST.sha256"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a public-safe Agentic-Jev SWE manager v2 result bundle."
    )
    parser.add_argument("run_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    result = prepare_swe_manager_publication(
        run_root=args.run_root,
        destination=args.destination,
    )
    print("Agentic-Jev SWE manager v2 publication prepared")
    print("path:", result["path"])
    print("manifest_sha256:", result["manifest_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
