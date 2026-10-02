from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file
from agent_workflow_comparative_eval import (
    build_paired_decision_report,
    make_paired_decision_trial,
)

from .agentic_jev import _receipt_summary, _receipt_values, jev_bridged_tool
from .agentic_jev_decision_v4 import (
    SOURCE_COMMIT as JEV_SKILL_COMMIT,
    decision_skill_path,
    decision_skill_sha256,
)
from .inspect_adjudication import resolve_latest_codex_cli
from .schema_contracts import validate_instance

STUDY_ID = "agentic-jev-swe-manager-v1"
STUDY_VERSION = "1.0.0-preregistered"
COHORT_SCHEMA = "agent-workflow-benchmark/agentic-jev-swe-manager-cohort/v1"
RUN_SCHEMA = "agent-workflow-benchmark/agentic-jev-swe-manager-run/v1"

INSPECT_EVALS_REPOSITORY = "UKGovernmentBEIS/inspect_evals"
INSPECT_EVALS_COMMIT = "190dfa27bc2e9b3e966ea6e8a682626d55b513c0"
INSPECT_EVAL_VERSION = "1-B"
SCORER_PATH = "src/inspect_evals/swe_lancer/scorers.py"
CSV_PATH = "src/inspect_evals/swe_lancer/data/all_swelancer_tasks.csv"
COHORT_SALT = "agentic-jev-swe-manager-v1"
TARGET_TASKS = 30

MODEL = "openai-api/codex-lb/gpt-6-luna"
MODEL_CONFIG = "gpt-6-luna"
REASONING_EFFORT = "high"
MODEL_ARGS = {"responses_api": True}

_FORBIDDEN_AGENT_JUDGMENT_KEYS = frozenset(
    {
        "agent_choice",
        "agent_confidence",
        "initial_agent_choice",
        "my_choice",
        "preferred_answer",
        "preferred_option",
        "selected_option",
        "selected_proposal_id",
        "verdict",
    }
)

SYSTEM_PROMPT = """Complete the official SWE-Lancer manager task from the supplied task prompt and repository.
The official task contract remains authoritative: inspect the repository as needed and write
/app/expensify/manager_decisions.json with the selected proposal ID. Use the installed Jev
decision-support skill when applicable and when its tool is available. Semantic evidence is
advisory; deterministic repository evidence remains authoritative.

After the manager_decisions.json file is written, your final visible response must be exactly one
JSON object with these fields:
- selected_proposal_id: the same proposal ID written to manager_decisions.json
- justification: an observable evidence-based rationale of 80-2000 characters
- evidence_refs: a JSON array with at least two requirement/proposal/repository evidence references
- tradeoff: the principal trade-off that determined the selection
- semantic_evidence_reconciliation: how semantic evidence was weighed against primary evidence;
  when no live semantic evidence was available or used, say that explicitly
- remaining_uncertainty: a concise string, or null

Do not expose private chain-of-thought. State decisive evidence, trade-offs, and uncertainty only.
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _read_prior_manager_ids(path: Path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise WorkflowError(
            "prior external-eval cohort is required so previously observed manager tasks "
            f"cannot enter the effectiveness cohort: {path}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid prior external cohort: {path}") from exc
    cohorts = value.get("cohorts")
    manager = cohorts.get("swe_lancer_manager_choice") if isinstance(cohorts, Mapping) else None
    if not isinstance(manager, list) or not manager:
        raise WorkflowError("prior external cohort has no SWE-Lancer manager task IDs")
    ids: list[str] = []
    for item in manager:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise WorkflowError("prior manager cohort contains an invalid entry")
        ids.append(str(item["id"]))
    return sorted(set(ids))


def select_fresh_manager_tasks(
    csv_path: Path,
    *,
    excluded_ids: Sequence[str],
    count: int = TARGET_TASKS,
    salt: str = COHORT_SALT,
) -> list[dict[str, str]]:
    if count < 1:
        raise ValueError("count must be positive")
    excluded = set(str(item) for item in excluded_ids)
    candidates: list[dict[str, str]] = []
    with Path(csv_path).open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"question_id", "variant", "set", "title"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise WorkflowError(
                "SWE-Lancer CSV missing selection fields: " + ", ".join(sorted(missing))
            )
        for row in reader:
            if row.get("variant") != "swe_manager" or row.get("set") != "diamond":
                continue
            sample_id = str(row.get("question_id") or "").strip()
            if not sample_id or sample_id in excluded:
                continue
            digest = hashlib.sha256(f"{salt}:{sample_id}".encode("utf-8")).hexdigest()
            candidates.append(
                {
                    "id": sample_id,
                    "title": str(row.get("title") or "").strip(),
                    "selection_digest": digest,
                    "first_arm": (
                        "control"
                        if int(digest[-1], 16) % 2 == 0
                        else "treatment"
                    ),
                }
            )
    candidates.sort(key=lambda item: (item["selection_digest"], item["id"]))
    if len(candidates) < count:
        raise WorkflowError(
            f"not enough fresh SWE-Lancer manager tasks: need {count}, found {len(candidates)}"
        )
    return candidates[:count]


def freeze_swe_manager_cohort(
    *,
    inspect_evals_checkout: Path,
    prior_cohort_path: Path,
    destination: Path,
    count: int = TARGET_TASKS,
) -> dict[str, Any]:
    destination = Path(destination)
    if destination.exists():
        raise WorkflowError(f"cohort is already frozen: {destination}")
    source = _require_pinned_checkout(inspect_evals_checkout)
    excluded = _read_prior_manager_ids(prior_cohort_path)
    selected = select_fresh_manager_tasks(
        Path(inspect_evals_checkout) / CSV_PATH,
        excluded_ids=excluded,
        count=count,
    )
    if set(excluded).intersection(item["id"] for item in selected):
        raise WorkflowError("fresh manager cohort overlaps previously observed tasks")
    selection_payload = {
        "salt": COHORT_SALT,
        "count": count,
        "excluded_ids": excluded,
        "selected_ids": [item["id"] for item in selected],
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
                json.dumps(selection_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "tasks": selected,
        "execution": {
            "epochs": 1,
            "paired_arms": ["control", "treatment"],
            "control": "current Jev decision skill installed; no live Jev tool",
            "treatment": "same skill plus live host-side Jev tool",
            "arm_order": "per-task deterministic counterbalancing from frozen selection digest",
            "score_source": "official Inspect Evals SWE-Lancer scorer",
            "outcome_dependent_stopping": False,
        },
        "claim_boundary": {
            "previously_observed_tasks_excluded": True,
            "selection_is_gold_blind": True,
            "fixed_n": True,
            "called_only_subsets_are_descriptive": True,
        },
    }
    validate_instance(record, COHORT_SCHEMA, artifact="SWE-Lancer Jev cohort")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), "sha256": sha256_file(destination), **record}


def load_swe_manager_cohort(path: Path, *, inspect_evals_checkout: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid SWE-Lancer Jev cohort: {path}") from exc
    validate_instance(value, COHORT_SCHEMA, artifact=str(path))
    source = _require_pinned_checkout(inspect_evals_checkout)
    frozen = value["source"]
    if frozen["commit"] != source["commit"]:
        raise WorkflowError("cohort Inspect Evals commit no longer matches checkout")
    if frozen["csv_sha256"] != source["csv_sha256"]:
        raise WorkflowError("cohort SWE-Lancer CSV identity changed")
    if frozen["scorer_source_sha256"] != source["scorer_sha256"]:
        raise WorkflowError("cohort official scorer identity changed")
    ids = [str(item["id"]) for item in value["tasks"]]
    if len(ids) != len(set(ids)) or len(ids) != int(value["selection"]["target_tasks"]):
        raise WorkflowError("cohort task identities are not unique/complete")
    prior = set(str(x) for x in value["selection"]["previously_observed_ids"])
    if prior.intersection(ids):
        raise WorkflowError("cohort contains a previously observed manager task")
    return value


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
    if (
        not isinstance(refs, list)
        or len(refs) < 2
        or not all(isinstance(item, str) and item.strip() for item in refs)
        or len(refs) != len(set(refs))
    ):
        raise WorkflowError("manager decision record requires at least two unique evidence_refs")
    for field in ("tradeoff", "semantic_evidence_reconciliation"):
        if not isinstance(value[field], str) or len(value[field].strip()) < 20:
            raise WorkflowError(f"manager decision record {field} is too short")
    remaining = value["remaining_uncertainty"]
    if remaining is not None and (not isinstance(remaining, str) or not remaining.strip()):
        raise WorkflowError("remaining_uncertainty must be a non-empty string or null")
    return {**value, "selected_proposal_id": selected_text}


def _forbidden_keys(value: object) -> list[str]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key).lower().replace("-", "_").strip()
                if key in _FORBIDDEN_AGENT_JUDGMENT_KEYS:
                    found.add(key)
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for child in value.values():
            result.extend(_string_values(child))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for child in value:
            result.extend(_string_values(child))
        return result
    return []


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_./-]{4,}", text.lower())
        if token
        not in {
            "that",
            "this",
            "with",
            "from",
            "have",
            "will",
            "your",
            "should",
            "must",
            "when",
            "what",
            "which",
            "their",
            "there",
        }
    }


def _section(prompt: str, tag: str) -> str:
    match = re.search(
        rf"<{re.escape(tag)}>\s*(.*?)\s*</{re.escape(tag)}>",
        prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _coverage(source: str, projected: str) -> float | None:
    source_tokens = _tokens(source)
    if not source_tokens:
        return None
    projected_tokens = _tokens(projected)
    return len(source_tokens & projected_tokens) / len(source_tokens)


def inspect_real_task_jev_context(
    receipt: Mapping[str, Any],
    *,
    prompt_text: str,
) -> dict[str, Any]:
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        return {"complete": False, "reason": "missing_request"}
    state = request.get("state")
    questions = request.get("questions")
    if not isinstance(state, Mapping) or not isinstance(questions, Mapping):
        return {"complete": False, "reason": "missing_state_or_questions"}
    projected = "\n".join(_string_values(state))
    title = _section(prompt_text, "title")
    description = _section(prompt_text, "description")
    proposals = _section(prompt_text, "proposals")
    coverage = {
        "title": _coverage(title, projected),
        "description": _coverage(description, projected),
        "proposals": _coverage(proposals, projected),
    }
    choice_questions = [
        str(key)
        for key, spec in questions.items()
        if isinstance(spec, Mapping) and str(spec.get("type")) == "choice"
    ]
    forbidden = _forbidden_keys(state)
    purpose = receipt.get("purpose")
    checks = {
        "title_coverage": coverage["title"] is not None and coverage["title"] >= 0.50,
        "description_coverage": coverage["description"] is not None and coverage["description"] >= 0.25,
        "proposal_coverage": coverage["proposals"] is not None and coverage["proposals"] >= 0.40,
        "choice_question_present": bool(choice_questions),
        "purpose_present": isinstance(purpose, str) and bool(purpose.strip()),
        "agent_judgment_keys_absent": not forbidden,
    }
    return {
        "complete": all(checks.values()),
        "checks": checks,
        "coverage": coverage,
        "choice_question_ids": choice_questions,
        "forbidden_agent_judgment_keys": forbidden,
        "state_sha256": receipt.get("state_sha256"),
        "questions_sha256": receipt.get("questions_sha256"),
        "request_sha256": receipt.get("request_sha256"),
        "thresholds": {"title": 0.50, "description": 0.25, "proposals": 0.40},
    }


def _build_solver(
    *,
    codex_version: str,
    treatment: bool,
    receipt_path: Path,
    jev_model: str | None,
) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError(
            "paired SWE-Lancer study requires agent-workflow-benchmark[agentic-jev]"
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
                tools=[jev_bridged_tool(receipt_path=receipt_path, model=jev_model)],
            )
        ]
    else:
        kwargs["bridged_tools"] = []
    return codex_cli(**kwargs)


def _manager_decision_capture_scorer() -> Any:
    try:
        from inspect_ai.scorer import Score, scorer
        from inspect_ai.util import sandbox
    except ImportError as exc:
        raise WorkflowError("paired SWE-Lancer study requires Inspect AI") from exc

    @scorer(metrics=[])
    def manager_decision_capture() -> Any:
        async def score(state: Any, target: Any) -> Any:
            selected: str | None = None
            error: str | None = None
            try:
                raw = await sandbox().read_file("/app/expensify/manager_decisions.json")
                parsed = json.loads(raw)
                if isinstance(parsed, Mapping) and parsed.get("selected_proposal_id") is not None:
                    selected = str(parsed["selected_proposal_id"])
            except Exception as exc:  # evidence capture must not replace official scoring
                error = type(exc).__name__
            return Score(
                value=1.0,
                answer="manager decision evidence captured",
                metadata={
                    "evidence_kind": "agent_workflow_manager_decision_capture",
                    "selected_proposal_id": selected,
                    "capture_error_class": error,
                },
            )

        return score

    return manager_decision_capture()


def _task_prompt(task: Any, sample_id: str) -> str:
    dataset = getattr(task, "dataset", None)
    for sample in dataset or []:
        if str(getattr(sample, "id", "")) != sample_id:
            continue
        chunks: list[str] = []
        for message in getattr(sample, "input", None) or []:
            text = getattr(message, "text", "")
            if callable(text):
                text = text()
            if text:
                chunks.append(str(text))
        return "\n".join(chunks)
    raise WorkflowError(f"cannot locate frozen SWE-Lancer sample in upstream task: {sample_id}")


def _final_assistant_text(log: Any) -> tuple[str | None, int]:
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1:
        return None, 0
    assistant: list[str] = []
    reasoning_blocks = 0
    for message in getattr(samples[0], "messages", None) or []:
        if str(getattr(message, "role", "")) != "assistant":
            continue
        text = getattr(message, "text", "")
        if callable(text):
            text = text()
        if text:
            assistant.append(str(text))
        content = getattr(message, "content", None)
        if isinstance(content, list):
            reasoning_blocks += sum(
                1 for item in content if str(getattr(item, "type", "")) == "reasoning"
            )
    return (assistant[-1] if assistant else None), reasoning_blocks


def _transcript_contains_secret(log: Any) -> bool:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return False
    samples = getattr(log, "samples", None) or []
    transcript = json.dumps(
        [
            getattr(message, "model_dump", lambda: {"text": str(message)})()
            for sample in samples
            for message in (getattr(sample, "messages", None) or [])
        ],
        ensure_ascii=False,
        default=str,
    )
    return api_key in transcript


def _score_parts(sample: Any) -> tuple[float | None, str | None, str | None]:
    scores = getattr(sample, "scores", None)
    values: list[Any] = []
    if isinstance(scores, Mapping):
        values.extend(scores.values())
    elif isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)):
        values.extend(scores)
    official: float | None = None
    applied_selected: str | None = None
    capture_error: str | None = None
    for score in values:
        metadata = getattr(score, "metadata", None)
        if not isinstance(metadata, Mapping):
            continue
        if metadata.get("variant") == "swe_manager" and "correct_option" in metadata:
            raw = getattr(score, "value", None)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                numeric = float(raw)
                if numeric in {0.0, 1.0}:
                    official = numeric
        if metadata.get("evidence_kind") == "agent_workflow_manager_decision_capture":
            selected = metadata.get("selected_proposal_id")
            if selected is not None:
                applied_selected = str(selected)
            error = metadata.get("capture_error_class")
            if error is not None:
                capture_error = str(error)
    return official, applied_selected, capture_error


def _sample_status(log: Any) -> tuple[str, str | None]:
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1:
        return "error", "SampleCountMismatch"
    error = getattr(samples[0], "error", None)
    if error:
        error_class = getattr(error, "type", None) or getattr(error, "error", None)
        return "error", str(error_class or type(error).__name__)
    return "success", None


def _sample_usage(sample: Any) -> dict[str, Any]:
    usage = getattr(sample, "model_usage", None)
    if isinstance(usage, Mapping):
        return json.loads(json.dumps(usage, default=str))
    return {}


def _sample_duration(sample: Any) -> float | None:
    for key in ("total_time", "working_time"):
        value = getattr(sample, key, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            return float(value)
    return None


def _run_arm(
    *,
    arm: str,
    sample_id: str,
    root: Path,
    codex_version: str,
    jev_model: str | None,
) -> tuple[Any, str]:
    try:
        import inspect_ai
        from inspect_evals.swe_lancer import swe_lancer
        from inspect_evals.swe_lancer.scorers import swe_lancer_scorer
    except ImportError as exc:
        raise WorkflowError(
            "paired SWE-Lancer study requires the pinned Inspect Evals checkout"
        ) from exc
    treatment = arm == "treatment"
    receipt_path = root / "jev-tool-receipts.jsonl"
    solver = _build_solver(
        codex_version=codex_version,
        treatment=treatment,
        receipt_path=receipt_path,
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
    return logs[0], prompt_text


def _arm_evidence(
    *,
    arm: str,
    log: Any,
    prompt_text: str,
    receipt_path: Path,
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
            decision_error = "visible decision selected_proposal_id differs from manager_decisions.json"
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
        successful = [item for item in receipts if item.get("status") == "success"]
        contexts = [
            inspect_real_task_jev_context(item, prompt_text=prompt_text)
            for item in successful
        ]
        evidence["jev"] = {
            "tool_calls": len(receipts),
            "successful_calls": len(successful),
            "context_complete": (
                all(item.get("complete") is True for item in contexts)
                if contexts
                else None
            ),
            "request_hashes": [
                str(item.get("request_sha256"))
                for item in successful
                if isinstance(item.get("request_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("request_sha256")))
            ],
            "receipt_summary": _receipt_summary(receipt_path),
            "context_evidence": contexts,
        }
    return evidence


def run_paired_swe_manager_study(
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
            "paired SWE-Lancer output root is not empty; preserve prior evidence and use a fresh root"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    cohort = load_swe_manager_cohort(
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
        "codex_version": codex_version,
    }

    trials: list[dict[str, Any]] = []
    sample_artifacts: list[dict[str, Any]] = []
    for index, entry in enumerate(cohort["tasks"]):
        sample_id = str(entry["id"])
        sample_root = output_root / "samples" / sample_id
        sample_root.mkdir(parents=True, exist_ok=False)
        first = str(entry["first_arm"])
        second = "treatment" if first == "control" else "control"
        logs: dict[str, Any] = {}
        prompts: dict[str, str] = {}
        for arm in (first, second):
            arm_root = sample_root / arm
            arm_root.mkdir(parents=True, exist_ok=False)
            log, prompt_text = _run_arm(
                arm=arm,
                sample_id=sample_id,
                root=arm_root,
                codex_version=codex_version,
                jev_model=jev_model,
            )
            logs[arm] = log
            prompts[arm] = prompt_text

        # Outcome/scorer evidence is inspected only after both paired arms have executed.
        control = _arm_evidence(
            arm="control",
            log=logs["control"],
            prompt_text=prompts["control"],
            receipt_path=sample_root / "control" / "jev-tool-receipts.jsonl",
        )
        treatment = _arm_evidence(
            arm="treatment",
            log=logs["treatment"],
            prompt_text=prompts["treatment"],
            receipt_path=sample_root / "treatment" / "jev-tool-receipts.jsonl",
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
    validate_instance(record, RUN_SCHEMA, artifact="paired SWE-Lancer Jev run")
    atomic_write_json(output_root / "run-manifest.json", record)
    return {"path": str(output_root / "run-manifest.json"), **record}
