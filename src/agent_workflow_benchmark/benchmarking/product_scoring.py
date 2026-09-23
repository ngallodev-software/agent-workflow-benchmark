from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import sha256_file

from .common import read_object


PRODUCT_SCORE_SCHEMA = "agent-workflow/benchmark-supplementary-score/v1"
PRODUCT_CONTRACT_SCHEMA = "agent-workflow/benchmark-supplementary-scoring-contract/v1"


def _index_checks(machine_components: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for component in machine_components:
        for check in component.get("checks", []):
            if isinstance(check, Mapping) and isinstance(check.get("id"), str):
                result[str(check["id"])] = check
    return result


def _component(machine_components: list[Mapping[str, Any]], dimension: str) -> Mapping[str, Any]:
    for item in machine_components:
        if item.get("dimension") == dimension:
            return item
    raise WorkflowError(f"product scoring requires machine dimension {dimension}")


def _check(
    id_: str,
    maximum: float,
    earned: float,
    detail: str,
    evidence: list[str],
) -> dict[str, Any]:
    earned = round(max(0.0, min(float(maximum), float(earned))), 4)
    return {
        "id": id_,
        "passed": abs(earned - float(maximum)) < 1e-9,
        "earned_points": earned,
        "max_points": float(maximum),
        "detail": detail,
        "evidence_references": evidence,
    }


def _dimension(contract: Mapping[str, Any], id_: str) -> Mapping[str, Any]:
    for item in contract["dimensions"]:
        if item["id"] == id_:
            return item
    raise WorkflowError(f"product scoring contract has no dimension {id_}")


def _rule_max(dimension: Mapping[str, Any], rule_id: str) -> float:
    for item in dimension["rules"]:
        if item["id"] == rule_id:
            return float(item["max_points"])
    raise WorkflowError(f"product scoring contract has no rule {rule_id}")


def _observations(stage: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    assessment = read_object(stage / "visual" / "assessment.json")
    observations = assessment.get("observations")
    if not isinstance(observations, dict):
        observations = {}
    checks = {
        str(item["id"]): item
        for item in assessment.get("checks", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    return observations, checks


def score_end_to_end_product(
    *,
    worktree: Path,
    stage: Path,
    machine_components: list[Mapping[str, Any]],
    contract: Mapping[str, Any],
    contract_path: Path,
) -> dict[str, Any]:
    contract_id = str(contract.get("id"))
    if contract_id not in {"end-to-end-product/v1", "end-to-end-product/v2"}:
        raise WorkflowError(f"unsupported supplementary scoring contract: {contract_id}")
    product_v2 = contract_id == "end-to-end-product/v2"
    checks = _index_checks(machine_components)
    observations, visual = _observations(stage)
    fixture_value = json.loads((worktree / "data" / "backlog.json").read_text(encoding="utf-8"))
    if not isinstance(fixture_value, list):
        raise WorkflowError("supplementary product scoring requires a list backlog fixture")
    expected_items = len(fixture_value)

    live = observations.get("live") if isinstance(observations.get("live"), Mapping) else {}
    item_count = live.get("item_count")
    rendered = isinstance(item_count, int) and item_count == expected_items
    runtime_clean = (
        int(live.get("console_error_count", 0) or 0) == 0
        and int(live.get("navigation_error_count", 0) or 0) == 0
    )

    result_dimensions: list[dict[str, Any]] = []

    def add_dimension(id_: str, items: list[dict[str, Any]]) -> None:
        definition = _dimension(contract, id_)
        earned = round(sum(float(item["earned_points"]) for item in items), 4)
        maximum = float(definition["max_points"])
        if abs(sum(float(item["max_points"]) for item in items) - maximum) > 1e-9:
            raise WorkflowError(f"product dimension {id_} rule weights do not total {maximum:g}")
        result_dimensions.append({
            "id": id_,
            "label": str(definition["label"]),
            "earned_points": earned,
            "max_points": maximum,
            "checks": items,
        })

    core_def = _dimension(contract, "core_computation_data")
    hidden = _component(machine_components, "hidden_functional")
    hidden_max = float(hidden["max_points"])
    hidden_earned = float(hidden["earned_points"])
    core_max = _rule_max(core_def, "product.core.hidden-functional-scaled")
    add_dimension("core_computation_data", [
        _check(
            "product.core.hidden-functional-scaled",
            core_max,
            hidden_earned / hidden_max * core_max if hidden_max else 0.0,
            f"scaled hidden-functional score {hidden_earned:g}/{hidden_max:g}",
            ["machine:hidden_functional"],
        )
    ])

    integration_def = _dimension(contract, "end_to_end_data_integration")
    load_ok = bool(checks.get("hidden.load", {}).get("passed")) and bool(checks.get("public.export-server", {}).get("passed"))
    add_dimension("end_to_end_data_integration", [
        _check(
            "product.integration.fixture-load",
            _rule_max(integration_def, "product.integration.fixture-load"),
            _rule_max(integration_def, "product.integration.fixture-load") if load_ok else 0,
            "fixture load plus public server contract pass" if load_ok else "fixture/server evidence incomplete",
            ["machine:hidden.load", "machine:public.export-server"],
        ),
        _check(
            "product.integration.render-expected-items",
            _rule_max(integration_def, "product.integration.render-expected-items"),
            _rule_max(integration_def, "product.integration.render-expected-items") if rendered else 0,
            f"browser rendered {item_count!r} of {expected_items} expected supplied items",
            ["visual:observations.live.item_count"],
        ),
        _check(
            "product.integration.populated-state",
            _rule_max(integration_def, "product.integration.populated-state"),
            _rule_max(integration_def, "product.integration.populated-state") if rendered else 0,
            "populated supplied-data state observed" if rendered else "populated supplied-data state was not observed",
            ["visual:observations.live.item_count"],
        ),
    ])

    interactions_def = _dimension(contract, "required_interactions")
    def visual_pass(id_: str) -> bool:
        return bool(visual.get(id_, {}).get("passed"))

    export_obs = observations.get("download") if isinstance(observations.get("download"), Mapping) else {}
    export_max = _rule_max(interactions_def, "product.interaction.export")
    if rendered and visual_pass("ui.download"):
        export_earned = export_max
    elif rendered and export_obs.get("rows") == expected_items and bool(export_obs.get("json_download")):
        export_earned = export_max / 2
    else:
        export_earned = 0.0

    state_obs = observations.get("empty_invalid") if isinstance(observations.get("empty_invalid"), Mapping) else {}
    state_max = _rule_max(interactions_def, "product.interaction.empty-invalid")
    state_passes = int(bool(state_obs.get("empty_ok"))) + int(bool(state_obs.get("invalid_ok")))
    state_earned = state_max if state_passes == 2 else (state_max / 2 if state_passes == 1 else 0.0)

    interaction_checks = [
        _check(
            "product.interaction.search-filter-sort",
            _rule_max(interactions_def, "product.interaction.search-filter-sort"),
            _rule_max(interactions_def, "product.interaction.search-filter-sort") if rendered and visual_pass("ui.search-filter-sort") else 0,
            "visible search/filter/sort check passed" if rendered and visual_pass("ui.search-filter-sort") else "item-dependent search/filter/sort evidence did not pass",
            ["visual:ui.search-filter-sort"],
        ),
        _check(
            "product.interaction.keyboard-detail",
            _rule_max(interactions_def, "product.interaction.keyboard-detail"),
            _rule_max(interactions_def, "product.interaction.keyboard-detail") if rendered and visual_pass("ui.keyboard-detail") else 0,
            "keyboard detail check passed" if rendered and visual_pass("ui.keyboard-detail") else "item-dependent keyboard detail evidence did not pass",
            ["visual:ui.keyboard-detail"],
        ),
        _check(
            "product.interaction.export",
            export_max,
            export_earned,
            f"download rows={export_obs.get('rows')!r}; expected={expected_items}; full_visual_pass={visual_pass('ui.download')}",
            ["visual:ui.download", "visual:observations.download"],
        ),
        _check(
            "product.interaction.empty-invalid",
            state_max,
            state_earned,
            f"empty_ok={bool(state_obs.get('empty_ok'))}; invalid_ok={bool(state_obs.get('invalid_ok'))}",
            ["visual:ui.empty-invalid", "visual:observations.empty_invalid"],
        ),
    ]
    if product_v2:
        feedback_max = _rule_max(interactions_def, "product.interaction.export-feedback")
        interaction_checks.append(
            _check(
                "product.interaction.export-feedback",
                feedback_max,
                feedback_max if visual_pass("ui.export-feedback") else 0,
                "visible export feedback passed" if visual_pass("ui.export-feedback") else "visible export feedback did not pass",
                ["visual:ui.export-feedback", "visual:observations.export_feedback"],
            )
        )
    add_dimension("required_interactions", interaction_checks)

    presentation_def = _dimension(contract, "presentation_accessibility")
    presentation_checks = [
        _check(
            "product.presentation.labels-landmark",
            _rule_max(presentation_def, "product.presentation.labels-landmark"),
            _rule_max(presentation_def, "product.presentation.labels-landmark") if visual_pass("ui.labels-landmark") else 0,
            "labels/landmark passed" if visual_pass("ui.labels-landmark") else "labels/landmark failed",
            ["visual:ui.labels-landmark"],
        ),
        _check(
            "product.presentation.visible-focus",
            _rule_max(presentation_def, "product.presentation.visible-focus"),
            _rule_max(presentation_def, "product.presentation.visible-focus") if visual_pass("ui.visible-focus") else 0,
            "visible focus passed" if visual_pass("ui.visible-focus") else "visible focus failed",
            ["visual:ui.visible-focus"],
        ),
        _check(
            "product.presentation.responsive",
            _rule_max(presentation_def, "product.presentation.responsive"),
            _rule_max(presentation_def, "product.presentation.responsive") if visual_pass("ui.responsive") else 0,
            "responsive/no-overflow passed" if visual_pass("ui.responsive") else "responsive/no-overflow failed",
            ["visual:ui.responsive"],
        ),
        _check(
            "product.presentation.populated-data",
            _rule_max(presentation_def, "product.presentation.populated-data"),
            _rule_max(presentation_def, "product.presentation.populated-data") if rendered else 0,
            f"populated presentation observable={rendered}",
            ["visual:observations.live.item_count"],
        ),
        _check(
            "product.presentation.clean-runtime",
            _rule_max(presentation_def, "product.presentation.clean-runtime"),
            _rule_max(presentation_def, "product.presentation.clean-runtime") if runtime_clean else 0,
            f"console_errors={live.get('console_error_count', 0)}; navigation_errors={live.get('navigation_error_count', 0)}",
            ["visual:observations.live"],
        ),
    ]
    if product_v2:
        for rule_id, visual_id, detail in (
            ("product.presentation.factor-descriptions", "ui.factor-descriptions", "hover/focus factor descriptions"),
            ("product.presentation.visual-hierarchy", "ui.visual-hierarchy", "priority hierarchy and selected state"),
            ("product.presentation.status-styling", "ui.status-styling", "distinct status styling"),
        ):
            maximum = _rule_max(presentation_def, rule_id)
            passed = rendered and visual_pass(visual_id)
            presentation_checks.append(
                _check(
                    rule_id,
                    maximum,
                    maximum if passed else 0,
                    f"{detail} passed" if passed else f"{detail} did not pass",
                    [f"visual:{visual_id}"],
                )
            )
    add_dimension("presentation_accessibility", presentation_checks)

    if product_v2:
        debug_def = _dimension(contract, "debug_observability")
        debug_obs = observations.get("debug") if isinstance(observations.get("debug"), Mapping) else {}
        debug_checks: list[dict[str, Any]] = []
        debug_conditions = (
            (
                "product.debug.toggle-panel",
                bool(debug_obs.get("hidden_by_default")) and bool(debug_obs.get("visible_when_enabled")),
                "debug panel is hidden by default and visible when enabled",
            ),
            (
                "product.debug.bound-controls",
                bool(debug_obs.get("bound_controls_ok")),
                "debug panel enumerates required bound controls",
            ),
            (
                "product.debug.data-request",
                rendered and bool(debug_obs.get("request_ok")),
                "debug panel exposes source/request status/count and loaded item count",
            ),
            (
                "product.debug.state-errors",
                rendered and bool(debug_obs.get("state_updates")) and bool(debug_obs.get("errors_ok")) and bool(debug_obs.get("non_destructive")),
                "debug panel updates live state/errors without changing product results",
            ),
        )
        for rule_id, passed, detail in debug_conditions:
            maximum = _rule_max(debug_def, rule_id)
            debug_checks.append(
                _check(
                    rule_id,
                    maximum,
                    maximum if passed else 0,
                    detail if passed else f"{detail} did not pass",
                    ["visual:ui.debug-observability", "visual:observations.debug"],
                )
            )
        add_dimension("debug_observability", debug_checks)

    robust_def = _dimension(contract, "robustness_failure_handling")
    robustness = _component(machine_components, "robustness")
    robustness_max = float(robustness["max_points"])
    robustness_earned = float(robustness["earned_points"])
    robust_rule_max = _rule_max(robust_def, "product.robustness.scaled")
    add_dimension("robustness_failure_handling", [
        _check(
            "product.robustness.scaled",
            robust_rule_max,
            robustness_earned / robustness_max * robust_rule_max if robustness_max else 0,
            f"scaled robustness score {robustness_earned:g}/{robustness_max:g}",
            ["machine:robustness"],
        )
    ])

    eng_def = _dimension(contract, "engineering_completeness_traceability")
    scope = _component(machine_components, "scope_completeness")
    quality = _component(machine_components, "engineering_quality")
    source_max = float(scope["max_points"]) + float(quality["max_points"])
    source_earned = float(scope["earned_points"]) + float(quality["earned_points"])
    eng_rule_max = _rule_max(eng_def, "product.engineering.scope-quality-scaled")
    add_dimension("engineering_completeness_traceability", [
        _check(
            "product.engineering.scope-quality-scaled",
            eng_rule_max,
            source_earned / source_max * eng_rule_max if source_max else 0,
            f"scaled scope+engineering score {source_earned:g}/{source_max:g}",
            ["machine:scope_completeness", "machine:engineering_quality"],
        )
    ])

    total = round(sum(float(item["earned_points"]) for item in result_dimensions), 4)
    if abs(sum(float(item["max_points"]) for item in result_dimensions) - 100.0) > 1e-9:
        raise WorkflowError("supplementary product score dimensions must total 100")

    return {
        "schema": PRODUCT_SCORE_SCHEMA,
        "id": str(contract["id"]),
        "role": "supplementary",
        "winner_interaction": "none",
        "state": "scored",
        "score": total,
        "maximum_score": 100,
        "contract_sha256": sha256_file(contract_path),
        "scorer_version": str(contract["scorer_version"]),
        "dimensions": result_dimensions,
        "limitations": [str(item) for item in contract.get("limitations", [])],
        "error": None,
    }
