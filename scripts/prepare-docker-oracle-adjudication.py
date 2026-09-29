#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any

STUDY_ID = "routing-semantic-v1"
DATASET_VERSION = "routing-semantic-corpus-v1.0.0"
PROTOCOL_VERSION = "routing-semantic-oracle-v1.0.0"
CANONICAL_VIEW_SHA256 = "a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a"
CANONICAL_CORPUS_SHA256 = "e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280"
ADJUDICATION_PASS_SCHEMA_V1 = "agent-workflow-benchmark/decision-study-adjudication-pass/v1"
ADJUDICATION_PASS_SCHEMA_V2 = "agent-workflow-benchmark/decision-study-adjudication-pass/v2"
SUPPORTED_STUDIES = {"routing-semantic-v1", "routing-semantic-v2"}

TASK_CLASS = ["implementation", "diagnosis", "review", "documentation", "other"]
DECISION_ORDER = [
    "routing.task_class",
    "routing.interaction_required",
    "routing.semantic_risk",
]

BLOCKED_CODEX_CONFIG_KEYS = {
    "mcp_servers",
    "plugins",
    "browser_use",
    "notify",
    "model_instructions_file",
    "experimental_instructions_file",
    "developer_instructions",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def study_config(study_id: str) -> dict[str, Any]:
    if study_id not in SUPPORTED_STUDIES:
        raise SystemExit(f"unsupported adjudication study: {study_id}")
    module_path = (
        repo_root()
        / "modules"
        / "abc-adjudication"
        / f"{study_id}.module.json"
    )
    module = read_json(module_path)
    task = module.get("task") or {}
    if task.get("study_id") != study_id:
        raise SystemExit(f"adjudication module study_id mismatch: {module_path}")
    required = {
        str(item["id"]): item
        for item in module.get("required_files") or []
        if isinstance(item, dict) and item.get("id")
    }
    for required_id in ("oracle-view", "oracle-protocol", "routing-corpus"):
        if required_id not in required:
            raise SystemExit(
                f"adjudication module missing required file {required_id}: {module_path}"
            )
        if not required[required_id].get("sha256"):
            raise SystemExit(
                f"adjudication module must freeze SHA-256 for {required_id}: {module_path}"
            )
    output = module.get("output") or {}
    pass_schema = output.get("pass_schema")
    if pass_schema not in {ADJUDICATION_PASS_SCHEMA_V1, ADJUDICATION_PASS_SCHEMA_V2}:
        raise SystemExit(
            f"unsupported adjudication pass schema in {module_path}: {pass_schema!r}"
        )
    prompt = module.get("prompt") or {}
    template = prompt.get("template")
    if not isinstance(template, str) or not template:
        raise SystemExit(f"adjudication module has no prompt template: {module_path}")
    return {
        "module_path": module_path,
        "study_id": study_id,
        "dataset_version": str(task.get("dataset_version") or ""),
        "protocol_version": str(task.get("protocol_version") or ""),
        "prompt_template": template,
        "pass_schema": pass_schema,
        "view_source_path": str(required["oracle-view"]["source_path"]),
        "view_sha256": str(required["oracle-view"]["sha256"]),
        "protocol_source_path": str(required["oracle-protocol"]["source_path"]),
        "protocol_sha256": str(required["oracle-protocol"]["sha256"]),
        "corpus_source_path": str(required["routing-corpus"]["source_path"]),
        "corpus_sha256": str(required["routing-corpus"]["sha256"]),
    }


def justification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decisive_case_evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 320,
                },
            },
            "rubric_rule": {
                "type": "string",
                "minLength": 1,
                "maxLength": 320,
            },
            "ambiguity": {
                "type": "string",
                "enum": ["none", "material", "insufficient_evidence"],
            },
        },
        "required": [
            "decisive_case_evidence",
            "rubric_rule",
            "ambiguity",
        ],
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def copy_private(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)


def expected_records(view: dict[str, Any]) -> list[dict[str, Any]]:
    schema = view.get("schema")
    result: list[dict[str, Any]] = []
    for raw in view.get("cases", []):
        if not isinstance(raw, dict):
            raise SystemExit("adjudication view contains a non-object case")
        case_id = raw.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise SystemExit("adjudication view case is missing case_id")
        if schema == "agent-workflow-comparative-eval/oracle-authoring-view/v1":
            eligible = raw.get("oracle_eligible")
            if not isinstance(eligible, dict):
                raise SystemExit(f"{case_id}: missing oracle_eligible")
            decision_ids = [
                decision_id
                for decision_id in DECISION_ORDER
                if eligible.get(decision_id) is True
            ]
        elif schema == "agent-workflow-benchmark/decision-study-oracle-dispute-view/v1":
            disputed = raw.get("disputed_decision_ids")
            if not isinstance(disputed, list):
                raise SystemExit(f"{case_id}: missing disputed_decision_ids")
            decision_ids = [
                decision_id for decision_id in DECISION_ORDER if decision_id in disputed
            ]
        else:
            raise SystemExit(f"unsupported adjudication view schema: {schema!r}")
        if not decision_ids:
            raise SystemExit(f"{case_id}: no decision seams assigned")
        result.append({"case_id": case_id, "decision_ids": decision_ids})
    return result


def decision_schema(decision_id: str) -> dict[str, Any]:
    if decision_id == "routing.task_class":
        return {"type": "string", "enum": TASK_CLASS}
    if decision_id == "routing.interaction_required":
        return {"type": "boolean"}
    if decision_id == "routing.semantic_risk":
        return {"type": "integer", "minimum": 0, "maximum": 2}
    raise SystemExit(f"unsupported decision seam: {decision_id}")


def model_output_schema(
    records: list[dict[str, Any]],
    *,
    pass_schema: str = ADJUDICATION_PASS_SCHEMA_V1,
) -> dict[str, Any]:
    grouped: dict[tuple[str, ...], list[str]] = {}
    for record in records:
        decision_ids = tuple(record["decision_ids"])
        grouped.setdefault(decision_ids, []).append(record["case_id"])

    shape_variants: list[dict[str, Any]] = []
    for decision_ids, case_ids in grouped.items():
        shape_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "case_id": {"type": "string", "enum": case_ids},
                    "labels": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            decision_id: decision_schema(decision_id)
                            for decision_id in decision_ids
                        },
                        "required": list(decision_ids),
                    },
                    **(
                        {
                            "justifications": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    decision_id: justification_schema()
                                    for decision_id in decision_ids
                                },
                                "required": list(decision_ids),
                            }
                        }
                        if pass_schema == ADJUDICATION_PASS_SCHEMA_V2
                        else {}
                    ),
                },
                "required": [
                    "case_id",
                    "labels",
                    *(
                        ["justifications"]
                        if pass_schema == ADJUDICATION_PASS_SCHEMA_V2
                        else []
                    ),
                ],
            }
        )

    item_schema = (
        shape_variants[0]
        if len(shape_variants) == 1
        else {"oneOf": shape_variants}
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "records": {
                "type": "array",
                "minItems": len(records),
                "maxItems": len(records),
                "uniqueItems": True,
                "items": item_schema,
            }
        },
        "required": ["records"],
    }


def render_prompt(adjudicator_id: str, *, study_id: str = STUDY_ID) -> str:
    config = study_config(study_id)
    template = (repo_root() / config["prompt_template"]).read_text(encoding="utf-8")
    return template.replace("{{ADJUDICATOR_ID}}", adjudicator_id)


def prepare_agent(
    *,
    destination: Path,
    view_path: Path,
    protocol_path: Path,
    adjudicator_id: str,
    study_id: str = STUDY_ID,
) -> dict[str, Any]:
    input_dir = destination / "input"
    output_dir = destination / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(input_dir, stat.S_IRWXU)
    os.chmod(output_dir, stat.S_IRWXU)

    config = study_config(study_id)
    view = read_json(view_path)
    records = expected_records(view)
    view_sha256 = sha256_file(view_path)

    copy_private(view_path, input_dir / "oracle-view.json")
    copy_private(protocol_path, input_dir / "oracle-protocol.md")
    (input_dir / "START_PROMPT.md").write_text(
        render_prompt(adjudicator_id, study_id=study_id), encoding="utf-8"
    )
    os.chmod(input_dir / "START_PROMPT.md", stat.S_IRUSR | stat.S_IWUSR)

    metadata = {
        "study_id": view.get("study_id"),
        "dataset_version": view.get("dataset_version"),
        "protocol_version": view.get("protocol_version")
        or view.get("oracle_policy", {}).get("protocol_version"),
        "input_view_sha256": view_sha256,
        "adjudicator_id": adjudicator_id,
        "expected_records": records,
        "adjudication_pass_schema": config["pass_schema"],
    }
    if metadata["study_id"] != config["study_id"]:
        raise SystemExit(f"unexpected study_id in adjudication view: {metadata['study_id']!r}")
    if metadata["dataset_version"] != config["dataset_version"]:
        raise SystemExit(
            f"unexpected dataset_version in adjudication view: {metadata['dataset_version']!r}"
        )
    if metadata["protocol_version"] != config["protocol_version"]:
        raise SystemExit(
            f"unexpected protocol_version in adjudication view: {metadata['protocol_version']!r}"
        )

    write_json(input_dir / "pass-metadata.json", metadata)
    write_json(
        input_dir / "model-output.schema.json",
        model_output_schema(records, pass_schema=config["pass_schema"]),
    )

    return {
        "adjudicator_id": adjudicator_id,
        "view_sha256": view_sha256,
        "cases": len(records),
        "labels": sum(len(item["decision_ids"]) for item in records),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
    }


def prepare_ab(args: argparse.Namespace) -> None:
    config = study_config(args.study)
    root = args.root.resolve()
    comparative = args.comparative_eval_repo.resolve()
    if root.exists():
        if not args.force:
            raise SystemExit(f"adjudication root already exists: {root}")
        shutil.rmtree(root)

    view_path = comparative / config["view_source_path"]
    manifest_path = view_path.with_name("oracle-authoring-view.manifest.json")
    protocol_path = comparative / config["protocol_source_path"]
    corpus_path = comparative / config["corpus_source_path"]

    for path in (view_path, manifest_path, protocol_path, corpus_path):
        if not path.is_file():
            raise SystemExit(f"required comparative-eval artifact missing: {path}")

    manifest = read_json(manifest_path)
    view = read_json(view_path)
    actual_view_sha = sha256_file(view_path)
    actual_protocol_sha = sha256_file(protocol_path)
    actual_corpus_sha = sha256_file(corpus_path)

    for label, observed, expected in (
        ("oracle view", actual_view_sha, config["view_sha256"]),
        ("oracle protocol", actual_protocol_sha, config["protocol_sha256"]),
        ("routing corpus", actual_corpus_sha, config["corpus_sha256"]),
    ):
        if observed != expected:
            raise SystemExit(
                f"canonical {label} hash mismatch: expected {expected}, got {observed}"
            )
    if manifest.get("oracle_authoring_view", {}).get("sha256") != actual_view_sha:
        raise SystemExit("oracle authoring manifest does not match the view bytes")
    if manifest.get("corpus", {}).get("sha256") != actual_corpus_sha:
        raise SystemExit("oracle authoring manifest does not match the corpus bytes")
    if manifest.get("oracle_protocol", {}).get("sha256") != actual_protocol_sha:
        raise SystemExit("oracle authoring manifest does not match the protocol bytes")
    if len(view.get("cases", [])) != 120:
        raise SystemExit("frozen oracle authoring view must contain exactly 120 cases")

    coordinator = root / "coordinator"
    coordinator.mkdir(parents=True, exist_ok=True)
    copy_private(view_path, coordinator / "oracle-authoring-view.json")
    copy_private(protocol_path, coordinator / "oracle-protocol.md")
    copy_private(corpus_path, coordinator / "routing-corpus.json")
    copy_private(manifest_path, coordinator / "oracle-authoring-view.manifest.json")

    agents = [
        prepare_agent(
            destination=root / "a",
            view_path=view_path,
            protocol_path=protocol_path,
            adjudicator_id=args.adjudicator_a,
            study_id=args.study,
        ),
        prepare_agent(
            destination=root / "b",
            view_path=view_path,
            protocol_path=protocol_path,
            adjudicator_id=args.adjudicator_b,
            study_id=args.study,
        ),
    ]
    if agents[0]["view_sha256"] != agents[1]["view_sha256"]:
        raise SystemExit("A and B were not prepared from identical view bytes")

    run_manifest = {
        "schema": "agent-workflow-benchmark/docker-oracle-adjudication-run/v1",
        "study_id": config["study_id"],
        "dataset_version": config["dataset_version"],
        "protocol_version": config["protocol_version"],
        "adjudication_pass_schema": config["pass_schema"],
        "corpus_sha256": actual_corpus_sha,
        "oracle_authoring_view_sha256": actual_view_sha,
        "comparative_eval_repo": str(comparative),
        "agents": agents,
        "isolation": {
            "separate_input_mounts": True,
            "separate_output_mounts": True,
            "repository_mounted": False,
            "typesafe_credentials_allowed": False,
            "treatment_outputs_mounted": False,
        },
    }
    write_json(root / "run-manifest.json", run_manifest)
    print(json.dumps(run_manifest, indent=2, sort_keys=True))


def prepare_c(args: argparse.Namespace) -> None:
    config = study_config(args.study)
    root = args.root.resolve()
    dispute = args.dispute_view.resolve()
    if not dispute.is_file():
        raise SystemExit(f"C dispute view not found: {dispute}")

    view = read_json(dispute)
    if view.get("study_id") != config["study_id"]:
        raise SystemExit(
            f"C dispute view belongs to {view.get('study_id')!r}, expected {config['study_id']!r}"
        )
    cases = view.get("cases")
    if not isinstance(cases, list):
        raise SystemExit("C dispute view has no cases array")
    if not cases:
        marker = root / "coordinator" / "C_NOT_REQUIRED"
        marker.write_text("A/B adjudications have no disagreements.\n", encoding="utf-8")
        print(json.dumps({"requires_c": False, "disputed_cases": 0}))
        return

    protocol = root / "coordinator" / "oracle-protocol.md"
    if not protocol.is_file():
        raise SystemExit("coordinator oracle protocol missing; run prepare-ab first")

    destination = root / "c"
    if destination.exists():
        if not args.force:
            raise SystemExit(f"C adjudication directory already exists: {destination}")
        shutil.rmtree(destination)

    result = prepare_agent(
        destination=destination,
        view_path=dispute,
        protocol_path=protocol,
        adjudicator_id=args.adjudicator_c,
        study_id=args.study,
    )
    result["requires_c"] = True
    result["disputed_cases"] = len(cases)
    print(json.dumps(result, indent=2, sort_keys=True))


def validate_codex_config(args: argparse.Namespace) -> None:
    path = args.config.resolve()
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"invalid Codex config.toml {path}: {exc}") from exc

    blocked = sorted(BLOCKED_CODEX_CONFIG_KEYS.intersection(value))
    if blocked:
        raise SystemExit(
            "adjudicator config.toml contains context-expanding or side-effect keys "
            f"that are not permitted in the blinded container: {', '.join(blocked)}"
        )
    print(
        json.dumps(
            {
                "valid": True,
                "path": str(path),
                "blocked_keys_present": [],
                "note": "provider/auth/model configuration is retained; web search and shell network are overridden off by the container launcher",
            },
            indent=2,
            sort_keys=True,
        )
    )


def parser() -> argparse.ArgumentParser:
    root_default = repo_root() / ".adjudication" / STUDY_ID
    comparative_default = repo_root().parent / "agent-workflow-comparative-eval"

    result = argparse.ArgumentParser(
        description="Prepare isolated Docker inputs for routing semantic oracle adjudicators."
    )
    commands = result.add_subparsers(dest="command", required=True)

    ab = commands.add_parser("prepare-ab")
    ab.add_argument("--study", choices=sorted(SUPPORTED_STUDIES), default=STUDY_ID)
    ab.add_argument("--root", type=Path, default=root_default)
    ab.add_argument("--comparative-eval-repo", type=Path, default=comparative_default)
    ab.add_argument("--adjudicator-a", default="codex-a")
    ab.add_argument("--adjudicator-b", default="codex-b")
    ab.add_argument("--force", action="store_true")
    ab.set_defaults(func=prepare_ab)

    c = commands.add_parser("prepare-c")
    c.add_argument("--study", choices=sorted(SUPPORTED_STUDIES), default=STUDY_ID)
    c.add_argument("--root", type=Path, default=root_default)
    c.add_argument(
        "--dispute-view",
        type=Path,
        default=root_default / "coordinator" / "oracle-disputes-for-c.json",
    )
    c.add_argument("--adjudicator-c", default="codex-c")
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=prepare_c)

    config = commands.add_parser("validate-codex-config")
    config.add_argument("--config", type=Path, required=True)
    config.set_defaults(func=validate_codex_config)
    return result


def main() -> int:
    args = parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
