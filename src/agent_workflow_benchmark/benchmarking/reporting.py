from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_bytes, atomic_write_json, utc_now
from .common import read_object, write_manifest
from .contracts import BENCHMARK_REPORT_SCHEMA, validate_spec, validate_value
from .statistics import paired_bootstrap_interval


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _sum_complete(values: list[object]) -> float | None:
    if not values or any(value is None or isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return None
    return round(sum(float(value) for value in values), 6)


def _review_timing(run_dir: Path) -> dict[str, Any]:
    review_root = run_dir / "human-review" / "reviews"
    active: list[float] = []
    if review_root.is_dir():
        for path in sorted(review_root.glob("*.json")):
            value = read_object(path)
            seconds = value.get("active_review_seconds")
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
                active.append(float(seconds))
    return {
        "reviews_with_active_time": len(active),
        "human_active_review_seconds": round(sum(active), 6) if active else None,
    }


def _human_results(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    root = run_dir / "human-review" / ".blinding"
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*-unblinded.json")):
        value = read_object(path)
        for item in value.get("results", []):
            result.setdefault(str(item["pair_id"]), []).append(
                {"reviewer_id": value["reviewer_id"], **item}
            )
    return result


def _arm_dir(run_dir: Path, pair: Mapping[str, Any], arm: str) -> Path:
    return run_dir / "pairs" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / arm


def build_report(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    spec = validate_spec(Path(plan["coordinator"]["spec_path"]))
    if not (run_dir / "consolidation-receipt.json").is_file():
        raise WorkflowError("benchmark must be consolidated before reporting")
    reviews = _human_results(run_dir)
    run_state = read_object(run_dir / "run.json")
    minimum_reviewers = int(spec["visual"]["minimum_reviewers"][plan["claim_level"]])
    pair_reports: list[dict[str, Any]] = []
    arm_aggregates: dict[str, dict[str, list[float]]] = {
        "control_raw": {"machine": [], "eligible_machine": [], "human": [], "composite": [], "wall": [], "measured": [], "active": [], "visual": [], "verification": [], "tokens": [], "provider_cost": [], "local_cost": [], "subscription_cost": []},
        "workflow_full": {"machine": [], "eligible_machine": [], "human": [], "composite": [], "wall": [], "measured": [], "active": [], "visual": [], "verification": [], "tokens": [], "provider_cost": [], "local_cost": [], "subscription_cost": []},
    }
    eligible_pairs = 0
    complete_human_pairs = 0
    for pair in plan["pairs"]:
        pair_reviews = reviews.get(str(pair["pair_id"]), [])
        pair_state = read_object(
            run_dir / "pair-state" / str(pair["case_id"]) / f"r{int(pair['repetition']):02d}" / "pair.json"
        )
        human_by_arm: dict[str, list[float]] = {"control_raw": [], "workflow_full": []}
        blocking_by_arm: dict[str, list[str]] = {"control_raw": [], "workflow_full": []}
        preferences: list[str] = []
        for review in pair_reviews:
            for arm, score in review["arm_scores"].items():
                human_by_arm[arm].append(float(score))
            preferred = review.get("preference_arm")
            if preferred:
                preferences.append(str(preferred))
            for defect in review.get("blocking_defects", []):
                if isinstance(defect, dict):
                    arm = defect.get("arm")
                    if arm in blocking_by_arm:
                        blocking_by_arm[arm].append(str(defect.get("description", "blocking defect")))
                elif isinstance(defect, str):
                    blocking_by_arm["control_raw"].append(defect)
                    blocking_by_arm["workflow_full"].append(defect)
        human_complete = len(pair_reviews) >= minimum_reviewers
        if human_complete:
            complete_human_pairs += 1
        arm_results: dict[str, Any] = {}
        pair_machine_eligible = True
        for arm in ("control_raw", "workflow_full"):
            arm_dir = _arm_dir(run_dir, pair, arm)
            score = read_object(arm_dir / "score.json")
            arm_value = read_object(arm_dir / "arm.json")
            machine = score.get("machine_score")
            machine_eligible = score["eligibility"]["state"] == "eligible" and machine is not None
            pair_machine_eligible = pair_machine_eligible and machine_eligible
            human = _mean(human_by_arm[arm]) if human_complete else None
            blocking = blocking_by_arm[arm]
            composite = None
            passing = None
            if machine_eligible and human is not None and not blocking:
                composite = round(
                    float(spec["composite"]["machine_weight"]) * float(machine)
                    + float(spec["composite"]["human_weight"]) * human,
                    4,
                )
                passing = (
                    float(machine) >= float(spec["composite"]["minimum_machine_score"])
                    and human >= float(spec["composite"]["minimum_human_score"])
                )
            usage = arm_value.get("usage", {})
            phase_metrics = [
                {
                    "phase_id": item["phase_id"],
                    "state": item["state"],
                    "phase_wall_seconds": item["phase_wall_seconds"],
                    "active_process_seconds": item["active_process_seconds"],
                    "provider_elapsed_seconds": item["provider_elapsed_seconds"],
                    "first_output_latency_seconds": item["first_output_latency_seconds"],
                    "queue_wait_seconds": item["queue_wait_seconds"],
                    "usage": item["usage"],
                }
                for item in arm_value["phases"]
            ]
            wall = round(sum(float(item["phase_wall_seconds"]) for item in arm_value["phases"]), 6)
            active = _sum_complete([item.get("active_process_seconds") for item in arm_value["phases"]])
            provider_elapsed = _sum_complete([item.get("provider_elapsed_seconds") for item in arm_value["phases"]])
            first_output = _sum_complete([item.get("first_output_latency_seconds") for item in arm_value["phases"]])
            queue_wait = _sum_complete([item.get("queue_wait_seconds") for item in arm_value["phases"]])
            capture_path = arm_dir / "visual" / "capture.json"
            capture = read_object(capture_path) if capture_path.is_file() else {}
            visual_seconds = capture.get("duration_seconds")
            verification_seconds = score.get("verification_wall_seconds")
            measured_values = [wall, visual_seconds, verification_seconds]
            measured_total = _sum_complete(measured_values)
            total_tokens = usage.get("provider_total_tokens")
            if total_tokens is None and usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
                total_tokens = usage["input_tokens"] + usage["output_tokens"]
            provider_cost = usage.get("provider_billed_cost")
            local_cost = usage.get("local_estimated_cost")
            subscription_cost = usage.get("subscription_allocated_cost")
            arm_results[arm] = {
                "eligibility": score["eligibility"],
                "machine_score": machine,
                "eligible_machine_score": machine if machine_eligible else None,
                "human_visual_score": human,
                "reviewers": len(pair_reviews),
                "blocking_visual_defects": blocking,
                "composite_score": composite,
                "passing": passing,
                "usage": usage,
                "wall_seconds": wall,
                "measured_total_seconds": measured_total,
                "timing": {
                    "task_phase_wall_seconds": wall,
                    "active_process_seconds": active,
                    "provider_elapsed_seconds": provider_elapsed,
                    "first_output_latency_seconds": first_output,
                    "queue_wait_seconds": queue_wait,
                    "visual_capture_seconds": visual_seconds,
                    "machine_verification_seconds": verification_seconds,
                    "measured_nonhuman_total_seconds": measured_total,
                },
                "phase_metrics": phase_metrics,
                "terminal_state": arm_value["state"],
            }
            aggregate = arm_aggregates[arm]
            if machine is not None:
                aggregate["machine"].append(float(machine))
            if machine_eligible:
                aggregate["eligible_machine"].append(float(machine))
            if human is not None:
                aggregate["human"].append(human)
            if composite is not None:
                aggregate["composite"].append(composite)
            aggregate["wall"].append(wall)
            if measured_total is not None:
                aggregate["measured"].append(measured_total)
            if active is not None:
                aggregate["active"].append(active)
            if isinstance(visual_seconds, (int, float)) and not isinstance(visual_seconds, bool):
                aggregate["visual"].append(float(visual_seconds))
            if isinstance(verification_seconds, (int, float)) and not isinstance(verification_seconds, bool):
                aggregate["verification"].append(float(verification_seconds))
            if total_tokens is not None:
                aggregate["tokens"].append(float(total_tokens))
            if provider_cost is not None:
                aggregate["provider_cost"].append(float(provider_cost))
            if local_cost is not None:
                aggregate["local_cost"].append(float(local_cost))
            if subscription_cost is not None:
                aggregate["subscription_cost"].append(float(subscription_cost))
        if pair_machine_eligible:
            eligible_pairs += 1
        pair_reports.append(
            {
                "pair_id": pair["pair_id"],
                "case_id": pair["case_id"],
                "repetition": pair["repetition"],
                "reviewers": len(pair_reviews),
                "human_review_complete": human_complete,
                "preferences": preferences,
                "selected_attempt": pair_state.get("selected_attempt", 1),
                "infrastructure_retry_count": pair_state.get("infrastructure_retry_count", 0),
                "timing": {
                    "pair_wall_seconds": pair_state["pair_wall_seconds"],
                    "pair_sum_arm_wall_seconds": pair_state["pair_sum_arm_wall_seconds"],
                    "pair_critical_path_seconds": pair_state["pair_critical_path_seconds"],
                    "pair_start_skew_seconds": pair_state["pair_start_skew_seconds"],
                },
                "arms": arm_results,
                "deltas": {
                    field: (
                        round(float(arm_results["workflow_full"][field]) - float(arm_results["control_raw"][field]), 4)
                        if arm_results["workflow_full"][field] is not None and arm_results["control_raw"][field] is not None
                        else None
                    )
                    for field in ("machine_score", "human_visual_score", "composite_score", "wall_seconds", "measured_total_seconds")
                },
            }
        )
    aggregates: dict[str, Any] = {}
    for arm, values in arm_aggregates.items():
        aggregates[arm] = {
            "mean_machine_score": _mean(values["machine"]),
            "mean_eligible_machine_score": _mean(values["eligible_machine"]),
            "mean_human_visual_score": _mean(values["human"]),
            "mean_composite_score": _mean(values["composite"]),
            "mean_wall_seconds": _mean(values["wall"]),
            "mean_measured_nonhuman_total_seconds": _mean(values["measured"]),
            "mean_active_process_seconds": _mean(values["active"]),
            "mean_visual_capture_seconds": _mean(values["visual"]),
            "mean_machine_verification_seconds": _mean(values["verification"]),
            "mean_total_tokens": _mean(values["tokens"]),
            "mean_provider_billed_cost": _mean(values["provider_cost"]),
            "mean_local_estimated_cost": _mean(values["local_cost"]),
            "mean_subscription_allocated_cost": _mean(values["subscription_cost"]),
            "eligible_machine_results": len(values["eligible_machine"]),
            "complete_composites": len(values["composite"]),
        }
    delta_fields = {
        "machine_score": [], "human_visual_score": [], "composite_score": [],
        "wall_seconds": [], "measured_total_seconds": [], "provider_total_tokens": [],
        "provider_billed_cost": [], "local_estimated_cost": [], "qualified_pass": [],
    }
    for item in pair_reports:
        control = item["arms"]["control_raw"]
        workflow = item["arms"]["workflow_full"]
        for field in ("machine_score", "human_visual_score", "composite_score", "wall_seconds", "measured_total_seconds"):
            if control.get(field) is not None and workflow.get(field) is not None:
                delta_fields[field].append(float(workflow[field]) - float(control[field]))
        for field in ("provider_total_tokens", "provider_billed_cost", "local_estimated_cost"):
            left = control.get("usage", {}).get(field)
            right = workflow.get("usage", {}).get(field)
            if left is not None and right is not None:
                delta_fields[field].append(float(right) - float(left))
        if control.get("passing") is not None and workflow.get("passing") is not None:
            delta_fields["qualified_pass"].append(float(int(bool(workflow["passing"])) - int(bool(control["passing"]))))
    confidence = float(spec["winner_policy"].get("confidence_level", 0.95))
    statistics_result = {
        field: paired_bootstrap_interval(values, label=f"{plan['run_id']}:{field}", confidence=confidence)
        for field, values in delta_fields.items()
    }
    minimum_pairs = int(spec["winner_policy"]["minimum_eligible_pairs"])
    winner: str | None = None
    result_state = "descriptive_only"
    if eligible_pairs == len(plan["pairs"]) and complete_human_pairs == len(plan["pairs"]):
        result_state = "complete"
        if spec["winner_policy"]["enabled"] and eligible_pairs >= minimum_pairs:
            composite_ci = statistics_result["composite_score"]
            machine_ci = statistics_result["machine_score"]
            human_ci = statistics_result["human_visual_score"]
            threshold = float(spec["winner_policy"]["minimum_composite_delta"])
            max_machine_regression = float(spec["winner_policy"].get("max_machine_regression", 3))
            max_human_regression = float(spec["winner_policy"].get("max_human_regression", 3))
            if (
                composite_ci["lower"] is not None
                and float(composite_ci["lower"]) >= threshold
                and machine_ci["lower"] is not None
                and float(machine_ci["lower"]) >= -max_machine_regression
                and human_ci["lower"] is not None
                and float(human_ci["lower"]) >= -max_human_regression
            ):
                winner = "workflow_full"
            elif (
                composite_ci["upper"] is not None
                and float(composite_ci["upper"]) <= -threshold
                and machine_ci["upper"] is not None
                and float(machine_ci["upper"]) <= max_machine_regression
                and human_ci["upper"] is not None
                and float(human_ci["upper"]) <= max_human_regression
            ):
                winner = "control_raw"
            else:
                result_state = "no_winner"
        elif not spec["winner_policy"]["enabled"]:
            result_state = "complete_no_winner_policy"
        else:
            result_state = "descriptive_only"
    elif complete_human_pairs < len(plan["pairs"]):
        result_state = "awaiting_human_review"
    report = {
        "schema": BENCHMARK_REPORT_SCHEMA,
        "run_id": plan["run_id"],
        "benchmark_id": plan["benchmark_id"],
        "benchmark_version": plan["benchmark_version"],
        "generated_at": utc_now(),
        "claim_level": plan["claim_level"],
        "state": result_state,
        "winner": winner,
        "eligible_pairs": eligible_pairs,
        "total_pairs": len(plan["pairs"]),
        "human_complete_pairs": complete_human_pairs,
        "minimum_reviewers": minimum_reviewers,
        "composite": spec["composite"],
        "winner_policy": spec["winner_policy"],
        "operating_policy": plan["operating_policy"],
        "statistics": statistics_result,
        "cost_policy": {
            "authentication_mode": plan["executor"]["authentication"]["mode"],
            "billing_mode": plan["executor"]["billing"]["mode"],
            "provider_billed_cost_semantics": plan["executor"]["billing"]["provider_billed_cost_semantics"],
            "subscription_plan": plan["executor"]["billing"].get("subscription_plan"),
            "subscription_allocation": plan["executor"]["billing"].get("subscription_allocation"),
            "price_catalog_id": plan["executor"].get("price_catalog_id"),
        },
        "timing": {
            "run_created_at": run_state.get("created_at"),
            "run_started_at": run_state.get("started_at"),
            "automated_pipeline_completed_at": run_state.get("automated_pipeline_completed_at"),
            "benchmark_execution_wall_seconds": run_state.get("benchmark_execution_wall_seconds"),
            "execution_stage_wall_seconds": run_state.get("execution_stage_wall_seconds"),
            "visual_capture_stage_wall_seconds": run_state.get("visual_capture_stage_wall_seconds"),
            "machine_scoring_stage_wall_seconds": run_state.get("machine_scoring_stage_wall_seconds"),
            "consolidation_stage_wall_seconds": run_state.get("consolidation_stage_wall_seconds"),
            "reporting_stage_wall_seconds": run_state.get("reporting_stage_wall_seconds"),
            "automated_pipeline_wall_seconds": run_state.get("automated_pipeline_wall_seconds"),
            **_review_timing(run_dir),
        },
        "aggregates": aggregates,
        "pairs": pair_reports,
        "limitations": [
            "Efficiency metrics are descriptive and do not add machine-quality points.",
            "A winner is not declared unless the frozen winner policy is enabled and its sample threshold is met.",
            "Observed machine scores remain reportable when a guardrail fails; only eligible machine scores may contribute to composites or winner claims.",
            "Publication eligibility additionally requires verified filesystem/oracle isolation and publication-verified visual runtime evidence.",
            "Subscription runs report provider-billed cost as unavailable; API-equivalent estimates and optional subscription allocations are separate fields.",
        ],
    }
    validate_value(report, BENCHMARK_REPORT_SCHEMA, "benchmark report")
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# Comparative benchmark report — {report['run_id']}",
        "",
        f"- Benchmark: `{report['benchmark_id']}` v{report['benchmark_version']}",
        f"- State: **{report['state']}**",
        f"- Eligible pairs: {report['eligible_pairs']} / {report['total_pairs']}",
        f"- Human-complete pairs: {report['human_complete_pairs']} / {report['total_pairs']}",
        f"- Winner: `{report['winner'] or 'none'}`",
        f"- Operating policy: `{report['operating_policy']['policy']['policy_id']}`",
        f"- Authentication: `{report['cost_policy']['authentication_mode']}`; billing: `{report['cost_policy']['billing_mode']}`",
        "",
        "## Arm aggregates",
        "",
        "| Arm | Machine | Human visual | Composite | Task wall | Measured total | Tokens | Provider cost | Local estimate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("control_raw", "workflow_full"):
        item = report["aggregates"][arm]
        def show(value: Any) -> str:
            return "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)
        lines.append(
            "| " + " | ".join(
                [
                    f"`{arm}`",
                    show(item["mean_machine_score"]),
                    show(item["mean_human_visual_score"]),
                    show(item["mean_composite_score"]),
                    show(item["mean_wall_seconds"]),
                    show(item["mean_measured_nonhuman_total_seconds"]),
                    show(item["mean_total_tokens"]),
                    show(item["mean_provider_billed_cost"]),
                    show(item["mean_local_estimated_cost"]),
                ]
            ) + " |"
        )
    lines.extend(["", "## Pair results", ""])
    for pair in report["pairs"]:
        lines.append(f"### {pair['pair_id']}")
        lines.append("")
        timing = pair["timing"]
        lines.append(
            f"Pair wall: {timing['pair_wall_seconds']}s; critical path: "
            f"{timing['pair_critical_path_seconds']}s; start skew: "
            f"{timing['pair_start_skew_seconds']}s."
        )
        lines.append("")
        lines.append("| Arm | Eligible | Machine | Human | Composite | Task wall | Measured total |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for arm in ("control_raw", "workflow_full"):
            item = pair["arms"][arm]
            lines.append(
                f"| `{arm}` | {item['eligibility']['state']} | "
                f"{item['machine_score'] if item['machine_score'] is not None else '—'} | "
                f"{item['human_visual_score'] if item['human_visual_score'] is not None else '—'} | "
                f"{item['composite_score'] if item['composite_score'] is not None else '—'} | "
                f"{item['wall_seconds']} | "
                f"{item['measured_total_seconds'] if item['measured_total_seconds'] is not None else '—'} |"
            )
        lines.append("")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def write_report(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    run_dir = Path(plan["coordinator"]["run_dir"])
    report = build_report(plan_path)
    atomic_write_json(run_dir / "report.json", report)
    atomic_write_bytes(run_dir / "report.md", render_markdown(report).encode("utf-8"))
    write_manifest(run_dir)
    return report
