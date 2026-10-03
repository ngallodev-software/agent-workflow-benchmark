from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from importlib import metadata, resources
from pathlib import Path
from typing import Any

import agent_workflow.errors as agent_workflow_errors_module
import agent_workflow.util as agent_workflow_util_module
import agent_workflow_comparative_eval.paired_decisions as comparative_paired_decisions_module
from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file
from agent_workflow_comparative_eval import (
    build_paired_decision_report,
    make_paired_decision_trial,
)

from . import agentic_jev as agentic_jev_runtime
from . import agentic_jev_request_v2 as request_builder_module
from . import agentic_jev_swe_manager_v2 as manager_policy_module
from .agentic_jev import _receipt_summary, _receipt_values
from .agentic_jev_decision_v6 import (
    SOURCE_COMMIT as JEV_SKILL_COMMIT,
    decision_skill_path,
    decision_skill_sha256,
    decision_skill_interface_sha256,
)
from .agentic_jev_swe_manager_v1 import (
    _final_assistant_text,
    _manager_decision_capture_scorer,
    _sample_duration,
    _sample_status,
    _sample_usage,
    _score_parts,
    _task_prompt,
    _transcript_contains_secret,
)
from .agentic_jev_swe_manager_v2 import (
    POLICY_ID,
    POLICY_VERSION,
    inspect_manager_built_request,
    load_manager_authoritative_context,
    manager_jev_bridged_tool_v2,
)
from .inspect_adjudication import resolve_latest_codex_cli
from .schema_contracts import validate_instance

STUDY_ID = "agentic-jev-swe-manager-v2"
STUDY_VERSION = "2.0.0-preregistered"
COHORT_SCHEMA = "agent-workflow-benchmark/agentic-jev-swe-manager-cohort/v2"
RUN_SCHEMA = "agent-workflow-benchmark/agentic-jev-swe-manager-run/v2"
RUN_START_SCHEMA = "agent-workflow-benchmark/agentic-jev-swe-manager-run-start/v2"

INSPECT_EVALS_REPOSITORY = "UKGovernmentBEIS/inspect_evals"
INSPECT_EVALS_COMMIT = "190dfa27bc2e9b3e966ea6e8a682626d55b513c0"
INSPECT_EVAL_VERSION = "1-B"
SCORER_PATH = "src/inspect_evals/swe_lancer/scorers.py"
CSV_PATH = "src/inspect_evals/swe_lancer/data/all_swelancer_tasks.csv"
COHORT_SALT = STUDY_ID
TARGET_TASKS = 30

MODEL = "openai-api/codex-lb/gpt-6-luna"
MODEL_CONFIG = "gpt-6-luna"
REASONING_EFFORT = "high"
MODEL_ARGS = {"responses_api": True}

OBSERVED_IDS_ASSET = (
    "assets/agentic-jev-request-v2/observed-manager-ids-v2-study.json"
)

SYSTEM_PROMPT = """Complete the official SWE-Lancer manager task from the supplied task prompt and repository.
The official task contract remains authoritative: inspect the repository as needed and write
/app/expensify/manager_decisions.json with the selected proposal ID. Use installed skills when
they apply. Semantic evidence is advisory; deterministic repository evidence remains authoritative.

When a live host semantic checkpoint is available, follow the installed decision-support skill:
inspect the repository first, submit sourced repository evidence and explicit verification scope,
and use the checkpoint before finalizing the proposal. Do not manually summarize authoritative
task/proposal text into the checkpoint; the host policy injects it. If the checkpoint explicitly
permits a rebuild, gather materially new evidence before a changed revision.

After manager_decisions.json is written, your final visible response must be exactly one JSON
object with these fields:
- selected_proposal_id: the same proposal ID written to manager_decisions.json
- justification: an observable evidence-based rationale of 80-2000 characters
- evidence_refs: a JSON array with at least two unique evidence references. Each item may be a
  non-empty string or an object such as {"source":"path:line","fact":"observed fact"}.
- tradeoff: the principal trade-off that determined the selection
- semantic_evidence_reconciliation: how semantic evidence was weighed against primary evidence;
  when no live semantic evidence was available or used, say that explicitly
- remaining_uncertainty: a concise string, or null

Do not expose private chain-of-thought. State decisive evidence, trade-offs, and uncertainty only.
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _observed_registry_path() -> Path:
    resource = resources.files("agent_workflow_benchmark").joinpath(OBSERVED_IDS_ASSET)
    return Path(str(resource))


def load_observed_manager_ids() -> dict[str, Any]:
    path = _observed_registry_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid observed manager registry: {path}") from exc
    if not isinstance(value, dict):
        raise WorkflowError("observed manager registry must be an object")
    ids = value.get("ids")
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(item, str) and item.strip() for item in ids)
        or len(ids) != len(set(ids))
    ):
        raise WorkflowError("observed manager registry IDs are invalid")
    if int(value.get("unique_ids", -1)) != len(ids):
        raise WorkflowError("observed manager registry count is inconsistent")
    return {"path": str(path), "sha256": sha256_file(path), **value}


def _git_head(checkout: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkflowError(f"cannot resolve Inspect Evals git identity: {checkout}") from exc


def _require_pinned_checkout(checkout: Path) -> dict[str, str]:
    checkout = Path(checkout)
    observed = _git_head(checkout)
    if observed != INSPECT_EVALS_COMMIT:
        raise WorkflowError(
            f"Inspect Evals checkout must be {INSPECT_EVALS_COMMIT}; observed {observed}"
        )
    csv_path = checkout / CSV_PATH
    scorer_path = checkout / SCORER_PATH
    if not csv_path.is_file() or not scorer_path.is_file():
        raise WorkflowError("pinned Inspect Evals checkout is missing SWE-Lancer sources")
    return {
        "commit": observed,
        "csv_sha256": sha256_file(csv_path),
        "scorer_sha256": sha256_file(scorer_path),
    }


def _benchmark_source_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkflowError(
            "paired SWE-Lancer execution requires a benchmark git checkout with a resolvable HEAD"
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise WorkflowError(f"invalid benchmark git identity: {commit!r}")
    if dirty:
        raise WorkflowError(
            "benchmark checkout has tracked modifications; commit result-affecting code before execution"
        )
    return {
        "repository": "ngallodev-software/agent-workflow-benchmark",
        "commit": commit,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "host_bridge_sha256": sha256_file(Path(agentic_jev_runtime.__file__).resolve()),
        "request_builder_sha256": sha256_file(Path(request_builder_module.__file__).resolve()),
        "manager_policy_sha256": sha256_file(Path(manager_policy_module.__file__).resolve()),
        "observed_id_registry_sha256": sha256_file(_observed_registry_path()),
    }


def _dependency_code_identity() -> dict[str, str]:
    modules = {
        "agent_workflow.errors": agent_workflow_errors_module,
        "agent_workflow.util": agent_workflow_util_module,
        "agent_workflow_comparative_eval.paired_decisions": comparative_paired_decisions_module,
    }
    result: dict[str, str] = {}
    for name, module in modules.items():
        path = getattr(module, "__file__", None)
        if not isinstance(path, str) or not Path(path).is_file():
            raise WorkflowError(f"cannot hash runtime dependency module {name}")
        result[name] = sha256_file(Path(path).resolve())
    return result


def _installed_versions() -> dict[str, str | None]:
    names = (
        "agent-workflow-benchmark",
        "agent-workflow-comparative-eval",
        "agent-workflow",
        "inspect-ai",
        "inspect-swe",
        "inspect-evals",
        "typesafe-sdk",
    )
    result: dict[str, str | None] = {}
    for name in names:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def select_fresh_manager_tasks(
    csv_path: Path,
    *,
    excluded_ids: Sequence[str],
    count: int = TARGET_TASKS,
) -> list[dict[str, Any]]:
    excluded = set(map(str, excluded_ids))
    candidates: list[dict[str, Any]] = []
    with Path(csv_path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            sample_id = str(row.get("question_id") or "").strip()
            if (
                not sample_id
                or sample_id in excluded
                or str(row.get("variant") or "") != "swe_manager"
                or str(row.get("set") or "") != "diamond"
            ):
                continue
            digest = hashlib.sha256(f"{COHORT_SALT}:{sample_id}".encode()).hexdigest()
            candidates.append(
                {
                    "id": sample_id,
                    "title": str(row.get("title") or "").strip(),
                    "selection_digest": digest,
                    "first_arm": (
                        "control" if int(digest[-1], 16) % 2 == 0 else "treatment"
                    ),
                }
            )
    candidates.sort(key=lambda item: (item["selection_digest"], item["id"]))
    if len(candidates) < count:
        raise WorkflowError(
            f"not enough fresh SWE-Lancer manager tasks: need {count}, found {len(candidates)}"
        )
    return candidates[:count]


def freeze_swe_manager_v2_cohort(
    *,
    inspect_evals_checkout: Path,
    destination: Path,
    count: int = TARGET_TASKS,
) -> dict[str, Any]:
    destination = Path(destination)
    if destination.exists():
        raise WorkflowError(f"cohort is already frozen: {destination}")
    source = _require_pinned_checkout(inspect_evals_checkout)
    registry = load_observed_manager_ids()
    excluded = sorted(map(str, registry["ids"]))
    selected = select_fresh_manager_tasks(
        Path(inspect_evals_checkout) / CSV_PATH,
        excluded_ids=excluded,
        count=count,
    )
    selected_ids = [item["id"] for item in selected]
    if set(excluded).intersection(selected_ids):
        raise WorkflowError("fresh manager cohort overlaps previously observed tasks")
    selection_payload = {
        "salt": COHORT_SALT,
        "count": count,
        "excluded_ids": excluded,
        "selected_ids": selected_ids,
        "observed_id_registry_sha256": registry["sha256"],
    }
    record = {
        "schema": COHORT_SCHEMA,
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "created_at": _utc(),
        "source": {
            "repository": INSPECT_EVALS_REPOSITORY,
            "commit": source["commit"],
            "eval_version": INSPECT_EVAL_VERSION,
            "task": "inspect_evals/swe_lancer",
            "task_variant": "swe_manager",
            "split": "diamond",
            "csv_path": CSV_PATH,
            "csv_sha256": source["csv_sha256"],
            "scorer": "inspect_evals.swe_lancer.scorers.swe_lancer_scorer",
            "scorer_path": SCORER_PATH,
            "scorer_source_sha256": source["scorer_sha256"],
        },
        "selection": {
            "method": "ascending sha256(salt + ':' + official sample_id)",
            "salt": COHORT_SALT,
            "target_tasks": count,
            "gold_fields_used": False,
            "fields_read": ["question_id", "variant", "set", "title"],
            "previously_observed_ids": excluded,
            "selection_sha256": hashlib.sha256(
                json.dumps(selection_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "tasks": selected,
        "execution": {
            "epochs": 1,
            "paired_arms": ["control", "treatment"],
            "control": "decision skill v6 installed; no live Jev manager checkpoint",
            "treatment": (
                "same skill plus host-side deterministic manager request policy and "
                "live jev_manager_decision checkpoint"
            ),
            "treatment_expected_checkpoint_calls": 1,
            "treatment_max_changed_revisions_documented": 1,
            "arm_order": "per-task deterministic counterbalancing from frozen selection digest",
            "score_source": "official Inspect Evals SWE-Lancer scorer",
            "outcome_dependent_stopping": False,
            "observed_id_registry_sha256": registry["sha256"],
        },
        "claim_boundary": {
            "previously_observed_tasks_excluded": True,
            "selection_is_gold_blind": True,
            "fixed_n": True,
            "called_only_subsets_are_descriptive": True,
            "qualification_tasks_excluded_via_observed_registry": True,
        },
    }
    validate_instance(record, COHORT_SCHEMA, artifact="SWE-Lancer Jev v2 cohort")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), "sha256": sha256_file(destination), **record}


def load_swe_manager_v2_cohort(
    path: Path,
    *,
    inspect_evals_checkout: Path,
) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid SWE-Lancer Jev v2 cohort: {path}") from exc
    validate_instance(value, COHORT_SCHEMA, artifact=str(path))
    source = _require_pinned_checkout(inspect_evals_checkout)
    frozen = value["source"]
    if frozen["commit"] != source["commit"]:
        raise WorkflowError("cohort Inspect Evals commit no longer matches checkout")
    if frozen["csv_sha256"] != source["csv_sha256"]:
        raise WorkflowError("cohort SWE-Lancer CSV identity changed")
    if frozen["scorer_source_sha256"] != source["scorer_sha256"]:
        raise WorkflowError("cohort official scorer identity changed")
    registry = load_observed_manager_ids()
    ids = [str(item["id"]) for item in value["tasks"]]
    if len(ids) != len(set(ids)) or len(ids) != int(value["selection"]["target_tasks"]):
        raise WorkflowError("cohort task identities are not unique/complete")
    if set(registry["ids"]).intersection(ids):
        raise WorkflowError("cohort contains a previously observed manager task")
    if value["execution"].get("observed_id_registry_sha256") != registry["sha256"]:
        raise WorkflowError("cohort observed-ID registry identity changed")
    return value


def _normalize_evidence_ref(item: object) -> str:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if isinstance(item, Mapping):
        source = item.get("source", item.get("ref", item.get("path")))
        fact = item.get("fact", item.get("claim", item.get("observation")))
        if isinstance(source, str) and source.strip() and isinstance(fact, str) and fact.strip():
            return f"{source.strip()}: {fact.strip()}"
        return json.dumps(dict(item), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raise WorkflowError("evidence_refs entries must be strings or JSON objects")


def parse_manager_decision_record(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowError("final assistant response is not exactly one JSON object") from exc
    if not isinstance(value, dict):
        raise WorkflowError("final manager decision record must be an object")
    required = {
        "selected_proposal_id",
        "justification",
        "evidence_refs",
        "tradeoff",
        "semantic_evidence_reconciliation",
        "remaining_uncertainty",
    }
    if set(value) != required:
        raise WorkflowError(
            "manager decision record fields must be exactly: " + ", ".join(sorted(required))
        )
    selected = value["selected_proposal_id"]
    if isinstance(selected, bool) or not isinstance(selected, (str, int)):
        raise WorkflowError("selected_proposal_id must be a string or integer")
    selected_text = str(selected).strip()
    if not selected_text:
        raise WorkflowError("selected_proposal_id must not be empty")
    justification = value["justification"]
    if not isinstance(justification, str) or not 80 <= len(justification.strip()) <= 2000:
        raise WorkflowError("manager justification must be 80-2000 characters")
    refs = value["evidence_refs"]
    if not isinstance(refs, list) or len(refs) < 2:
        raise WorkflowError("manager decision record requires at least two evidence_refs")
    normalized_refs = [_normalize_evidence_ref(item) for item in refs]
    if len(normalized_refs) != len(set(normalized_refs)):
        raise WorkflowError("manager decision record evidence_refs must be unique")
    for field in ("tradeoff", "semantic_evidence_reconciliation"):
        if not isinstance(value[field], str) or len(value[field].strip()) < 20:
            raise WorkflowError(f"manager decision record {field} is too short")
    remaining = value["remaining_uncertainty"]
    if remaining is not None and (not isinstance(remaining, str) or not remaining.strip()):
        raise WorkflowError("remaining_uncertainty must be a non-empty string or null")
    return {
        **value,
        "selected_proposal_id": selected_text,
        "evidence_refs": normalized_refs,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            result.append(item)
    return result


def _build_solver(
    *,
    codex_version: str,
    treatment: bool,
    receipt_path: Path,
    history_path: Path,
    authoritative: Mapping[str, object],
    jev_model: str | None,
) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError(
            "paired SWE-Lancer v2 study requires agent-workflow-benchmark[agentic-jev]"
        ) from exc
    kwargs: dict[str, Any] = {
        "version": codex_version,
        "model_config": MODEL_CONFIG,
        "skills": [decision_skill_path().parent],
        "web_search": "disabled",
        "goals": False,
        "attempts": 1,
        "mcp_servers": [],
        "auto_review": False,
        "home_dir": "/tmp/codex-home",
        "system_prompt": SYSTEM_PROMPT,
        "config_overrides": {"approval_policy": "never", "web_search": "disabled"},
    }
    if treatment:
        kwargs["bridged_tools"] = [
            BridgedToolsSpec(
                name="jev",
                tools=[
                    manager_jev_bridged_tool_v2(
                        authoritative=authoritative,
                        receipt_path=receipt_path,
                        history_path=history_path,
                        model=jev_model,
                        study_id=STUDY_ID,
                    )
                ],
            )
        ]
    else:
        kwargs["bridged_tools"] = []
    return codex_cli(**kwargs)


def _run_arm(
    *,
    arm: str,
    sample_id: str,
    root: Path,
    codex_version: str,
    inspect_evals_checkout: Path,
    jev_model: str | None,
) -> tuple[Any, str, dict[str, object]]:
    try:
        import inspect_ai
        from inspect_evals.swe_lancer import swe_lancer
        from inspect_evals.swe_lancer.scorers import swe_lancer_scorer
    except ImportError as exc:
        raise WorkflowError(
            "paired SWE-Lancer v2 study requires the pinned Inspect Evals checkout"
        ) from exc
    authoritative = load_manager_authoritative_context(
        Path(inspect_evals_checkout) / CSV_PATH,
        sample_id=sample_id,
    )
    treatment = arm == "treatment"
    solver = _build_solver(
        codex_version=codex_version,
        treatment=treatment,
        receipt_path=root / "jev-tool-receipts.jsonl",
        history_path=root / "jev-request-history-v2.jsonl",
        authoritative=authoritative,
        jev_model=jev_model,
    )
    task = swe_lancer(
        task_variant="swe_manager",
        solver=solver,
        scorer=[swe_lancer_scorer(), _manager_decision_capture_scorer()],
        epochs=1,
        use_user_tool=False,
        use_per_task_images=False,
        debug=False,
    )
    prompt_text = _task_prompt(task, sample_id)
    logs = inspect_ai.eval(
        task,
        model=MODEL,
        model_args=dict(MODEL_ARGS),
        reasoning_effort=REASONING_EFFORT,
        sample_id=[sample_id],
        log_dir=str(root / "inspect-logs"),
        log_format="eval",
        max_samples=1,
        max_sandboxes=1,
        max_subprocesses=2,
        fail_on_error=False,
        retry_on_error=0,
        display="plain",
    )
    if len(logs) != 1:
        raise WorkflowError(f"{arm} sample {sample_id} produced {len(logs)} Inspect logs")
    return logs[0], prompt_text, authoritative


def _arm_evidence(
    *,
    arm: str,
    log: Any,
    authoritative: Mapping[str, object],
    receipt_path: Path,
    history_path: Path,
) -> dict[str, Any]:
    samples = getattr(log, "samples", None) or []
    sample = samples[0] if len(samples) == 1 else None
    status, error_class = _sample_status(log)
    final_text, reasoning_blocks = _final_assistant_text(log)
    decision_record: dict[str, Any] | None = None
    decision_error: str | None = None
    if final_text:
        try:
            decision_record = parse_manager_decision_record(final_text)
        except WorkflowError as exc:
            decision_error = str(exc)

    official_score: float | None = None
    applied_selected: str | None = None
    capture_error: str | None = None
    usage: dict[str, Any] = {}
    duration: float | None = None
    if sample is not None:
        official_score, applied_selected, capture_error = _score_parts(sample)
        usage = _sample_usage(sample)
        duration = _sample_duration(sample)

    if decision_record is not None and applied_selected is not None:
        if decision_record["selected_proposal_id"] != applied_selected:
            decision_error = (
                "visible decision selected_proposal_id differs from manager_decisions.json"
            )

    evidence: dict[str, Any] = {
        "status": status,
        "official_score": official_score,
        "selected_proposal_id": applied_selected,
        "decision_record": decision_record,
        "usage": usage,
        "duration_seconds": duration,
        "error_class": error_class,
        "inspect_log": getattr(log, "location", None),
        "decision_record_error": decision_error,
        "decision_capture_error": capture_error,
        "reasoning_blocks_observed": reasoning_blocks,
        "reasoning_content_exported": False,
        "api_key_absent_from_transcript": not _transcript_contains_secret(log),
    }

    if arm == "treatment":
        receipts = _receipt_values(receipt_path)
        history = _read_jsonl(history_path)
        successful_receipts = [item for item in receipts if item.get("status") == "success"]
        successful_history = [item for item in history if item.get("status") == "success"]
        contexts = [
            inspect_manager_built_request(item, authoritative=authoritative)
            for item in successful_history
        ]
        resolved_models = sorted({
            str(item.get("model")).strip()
            for item in successful_receipts
            if isinstance(item.get("model"), str) and str(item.get("model")).strip()
        })
        receipt_summary = _receipt_summary(receipt_path)
        evidence["jev"] = {
            "tool_calls": len(receipts),
            "successful_calls": len(successful_receipts),
            "context_complete": (
                all(item.get("complete") is True for item in contexts)
                if contexts
                else None
            ),
            "context_known_calls": len(contexts),
            "context_complete_calls": sum(item.get("complete") is True for item in contexts),
            "resolved_models": resolved_models,
            "service_token_records": int(receipt_summary["token_records"]),
            "service_input_tokens": float(receipt_summary["usage"]["input_tokens"]),
            "service_output_tokens": float(receipt_summary["usage"]["output_tokens"]),
            "service_total_tokens": float(receipt_summary["usage"]["provider_total_tokens"]),
            "service_duration_known_n": int(receipt_summary["duration_ms"]["n"]),
            "service_duration_ms_total": float(receipt_summary["duration_ms"]["total"]),
            "request_hashes": [
                str(item.get("request_sha256"))
                for item in successful_history
                if isinstance(item.get("request_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("request_sha256")))
            ],
            "receipt_summary": receipt_summary,
            "context_evidence": contexts,
        }
        evidence["request_history_records"] = len(history)
        evidence["request_history_successful"] = len(successful_history)
        evidence["revision_calls"] = sum(
            isinstance(item.get("revision"), Mapping)
            and isinstance(item["revision"].get("previous_decision_sha256"), str)
            and bool(item["revision"].get("previous_decision_sha256"))
            for item in successful_history
        )
    return evidence


def run_paired_swe_manager_v2_study(
    *,
    output_root: Path,
    cohort_path: Path,
    inspect_evals_checkout: Path,
    jev_model: str | None = None,
) -> dict[str, Any]:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise WorkflowError("TYPESAFE_API_KEY must be configured on the host")
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "paired SWE-Lancer v2 output root is not empty; preserve prior evidence and use a fresh root"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    cohort = load_swe_manager_v2_cohort(
        cohort_path,
        inspect_evals_checkout=inspect_evals_checkout,
    )
    codex = resolve_latest_codex_cli()
    codex_version = str(codex["resolved"])
    source = cohort["source"]
    source_common = {
        "task": source["task"],
        "task_variant": source["task_variant"],
        "inspect_evals_commit": source["commit"],
        "eval_version": source["eval_version"],
        "scorer": source["scorer"],
        "scorer_source_sha256": source["scorer_source_sha256"],
        "cohort_sha256": sha256_file(cohort_path),
    }
    runtime_common = {
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "skill_commit": JEV_SKILL_COMMIT,
        "skill_sha256": decision_skill_sha256(),
        "skill_interface_sha256": decision_skill_interface_sha256(),
        "codex_version": codex_version,
        "requested_jev_model": jev_model,
        "manager_policy_id": POLICY_ID,
        "manager_policy_version": POLICY_VERSION,
        "request_builder_version": request_builder_module.REQUEST_BUILDER_VERSION,
        "benchmark_source": _benchmark_source_identity(),
        "package_versions": _installed_versions(),
        "dependency_code_sha256": _dependency_code_identity(),
    }
    run_start = {
        "schema": RUN_START_SCHEMA,
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "created_at": _utc(),
        "cohort": {
            "path": str(Path(cohort_path).resolve()),
            "sha256": sha256_file(cohort_path),
            "samples": len(cohort["tasks"]),
        },
        "source": source_common,
        "runtime": {
            **runtime_common,
            "codex_cli": codex,
            "model_args": MODEL_ARGS,
            "requested_jev_model": jev_model,
        },
        "evidence_policy": {
            "failed_or_partial_execution_preserved": True,
            "inspect_logs_are_canonical_execution_evidence": True,
            "raw_jev_context_public": False,
            "credentials_public": False,
        },
    }
    validate_instance(run_start, RUN_START_SCHEMA, artifact="paired SWE-Lancer Jev v2 run start")
    start_path = output_root / "run-start.json"
    atomic_write_json(start_path, run_start)

    trials: list[dict[str, Any]] = []
    sample_artifacts: list[dict[str, Any]] = []
    for index, entry in enumerate(cohort["tasks"]):
        sample_id = str(entry["id"])
        sample_root = output_root / "samples" / sample_id
        sample_root.mkdir(parents=True, exist_ok=False)
        first = str(entry["first_arm"])
        second = "treatment" if first == "control" else "control"
        logs: dict[str, Any] = {}
        authoritative_by_arm: dict[str, Mapping[str, object]] = {}
        for arm in (first, second):
            arm_root = sample_root / arm
            arm_root.mkdir(parents=True, exist_ok=False)
            log, _prompt_text, authoritative = _run_arm(
                arm=arm,
                sample_id=sample_id,
                root=arm_root,
                codex_version=codex_version,
                inspect_evals_checkout=inspect_evals_checkout,
                jev_model=jev_model,
            )
            logs[arm] = log
            authoritative_by_arm[arm] = authoritative

        control = _arm_evidence(
            arm="control",
            log=logs["control"],
            authoritative=authoritative_by_arm["control"],
            receipt_path=sample_root / "control" / "jev-tool-receipts.jsonl",
            history_path=sample_root / "control" / "jev-request-history-v2.jsonl",
        )
        treatment = _arm_evidence(
            arm="treatment",
            log=logs["treatment"],
            authoritative=authoritative_by_arm["treatment"],
            receipt_path=sample_root / "treatment" / "jev-tool-receipts.jsonl",
            history_path=sample_root / "treatment" / "jev-request-history-v2.jsonl",
        )
        trial = make_paired_decision_trial(
            study_id=STUDY_ID,
            sample_id=sample_id,
            repetition=0,
            source=source_common,
            runtime=runtime_common,
            control=control,
            treatment=treatment,
        )
        atomic_write_json(sample_root / "paired-trial.json", trial)
        treatment_history = sample_root / "treatment" / "jev-request-history-v2.jsonl"
        sample_artifacts.append(
            {
                "sample_id": sample_id,
                "ordinal": index,
                "first_arm": first,
                "trial_path": str(sample_root / "paired-trial.json"),
                "control_inspect_log": control["inspect_log"],
                "treatment_inspect_log": treatment["inspect_log"],
                "control_decision_record_error": control["decision_record_error"],
                "treatment_decision_record_error": treatment["decision_record_error"],
                "control_api_key_absent": control["api_key_absent_from_transcript"],
                "treatment_api_key_absent": treatment["api_key_absent_from_transcript"],
                "treatment_request_history_records": treatment.get("request_history_records", 0),
                "treatment_revision_calls": treatment.get("revision_calls", 0),
                "treatment_request_history_sha256": (
                    sha256_file(treatment_history) if treatment_history.is_file() else None
                ),
            }
        )
        trials.append(trial)

    report = build_paired_decision_report(
        trials,
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        minimum_interval_n=10,
    )
    atomic_write_json(output_root / "paired-report.json", report)
    record = {
        "schema": RUN_SCHEMA,
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "created_at": _utc(),
        "cohort": {
            "path": str(Path(cohort_path).resolve()),
            "sha256": sha256_file(cohort_path),
            "samples": len(cohort["tasks"]),
        },
        "runtime": {
            **runtime_common,
            "codex_cli": codex,
            "model_args": MODEL_ARGS,
            "jev_model": jev_model,
        },
        "start_manifest": {
            "path": str(start_path),
            "sha256": sha256_file(start_path),
        },
        "execution": {
            "paired_samples_expected": len(cohort["tasks"]),
            "paired_samples_observed": len(trials),
            "official_scoring_enabled": True,
            "outcome_read_after_both_arms": True,
            "epochs": 1,
            "samples": sample_artifacts,
        },
        "report": report,
        "evidence_policy": {
            "inspect_logs_are_canonical_execution_evidence": True,
            "official_swe_lancer_score_is_canonical_correctness": True,
            "hidden_chain_of_thought_exported": False,
            "raw_jev_context_public": False,
            "raw_provider_http_public": False,
            "credentials_public": False,
        },
    }
    validate_instance(record, RUN_SCHEMA, artifact="paired SWE-Lancer Jev v2 run")
    atomic_write_json(output_root / "run-manifest.json", record)
    return {"path": str(output_root / "run-manifest.json"), **record}
