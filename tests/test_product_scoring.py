from __future__ import annotations

import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.product_scoring import score_end_to_end_product


def _component(dimension: str, earned: float, maximum: float, checks=None):
    return {
        "dimension": dimension,
        "earned_points": earned,
        "max_points": maximum,
        "checks": checks or [],
    }


def _machine_components() -> list[dict]:
    return [
        _component("hidden_functional", 36, 45, [
            {"id": "hidden.load", "passed": True},
        ]),
        _component("public_regression", 15, 15, [
            {"id": "public.export-server", "passed": True},
        ]),
        _component("robustness", 10, 10),
        _component("scope_completeness", 10, 10),
        _component("engineering_quality", 6, 10),
        _component("accessibility_ui", 2.5, 10),
    ]


def _contract(path: Path) -> dict:
    value = {
        "id": "end-to-end-product/v1",
        "scorer_version": "1.0.0",
        "dimensions": [
            {"id": "core_computation_data", "label": "Core", "max_points": 30, "rules": [{"id": "product.core.hidden-functional-scaled", "max_points": 30}]},
            {"id": "end_to_end_data_integration", "label": "Integration", "max_points": 20, "rules": [
                {"id": "product.integration.fixture-load", "max_points": 5},
                {"id": "product.integration.render-expected-items", "max_points": 10},
                {"id": "product.integration.populated-state", "max_points": 5},
            ]},
            {"id": "required_interactions", "label": "Interactions", "max_points": 20, "rules": [
                {"id": "product.interaction.search-filter-sort", "max_points": 6},
                {"id": "product.interaction.keyboard-detail", "max_points": 4},
                {"id": "product.interaction.export", "max_points": 6},
                {"id": "product.interaction.empty-invalid", "max_points": 4},
            ]},
            {"id": "presentation_accessibility", "label": "Presentation", "max_points": 15, "rules": [
                {"id": "product.presentation.labels-landmark", "max_points": 4},
                {"id": "product.presentation.visible-focus", "max_points": 3},
                {"id": "product.presentation.responsive", "max_points": 4},
                {"id": "product.presentation.populated-data", "max_points": 3},
                {"id": "product.presentation.clean-runtime", "max_points": 1},
            ]},
            {"id": "robustness_failure_handling", "label": "Robustness", "max_points": 5, "rules": [{"id": "product.robustness.scaled", "max_points": 5}]},
            {"id": "engineering_completeness_traceability", "label": "Engineering", "max_points": 10, "rules": [{"id": "product.engineering.scope-quality-scaled", "max_points": 10}]},
        ],
        "limitations": ["supplementary"],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def test_product_score_gates_item_dependent_credit_when_browser_renders_zero(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    stage = tmp_path / "stage"
    (worktree / "data").mkdir(parents=True)
    (stage / "visual").mkdir(parents=True)
    (worktree / "data" / "backlog.json").write_text(json.dumps([{"id": str(i)} for i in range(6)]), encoding="utf-8")
    (stage / "visual" / "assessment.json").write_text(json.dumps({
        "observations": {
            "live": {"item_count": 0, "console_error_count": 3, "navigation_error_count": 0},
            "download": {"rows": None, "json_download": False},
            "empty_invalid": {"empty_ok": False, "invalid_ok": False},
        },
        "checks": [
            {"id": "ui.labels-landmark", "passed": False},
            {"id": "ui.search-filter-sort", "passed": False},
            {"id": "ui.keyboard-detail", "passed": False},
            {"id": "ui.visible-focus", "passed": True},
            {"id": "ui.responsive", "passed": True},
            {"id": "ui.download", "passed": False},
            {"id": "ui.empty-invalid", "passed": False},
        ],
    }), encoding="utf-8")
    contract_path = tmp_path / "contract.json"
    contract = _contract(contract_path)
    score = score_end_to_end_product(
        worktree=worktree,
        stage=stage,
        machine_components=_machine_components(),
        contract=contract,
        contract_path=contract_path,
    )
    assert score["score"] == 49
    integration = next(x for x in score["dimensions"] if x["id"] == "end_to_end_data_integration")
    assert integration["earned_points"] == 5


def test_product_score_awards_partial_export_and_invalid_state(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    stage = tmp_path / "stage"
    (worktree / "data").mkdir(parents=True)
    (stage / "visual").mkdir(parents=True)
    (worktree / "data" / "backlog.json").write_text(json.dumps([{"id": str(i)} for i in range(6)]), encoding="utf-8")
    (stage / "visual" / "assessment.json").write_text(json.dumps({
        "observations": {
            "live": {"item_count": 6, "console_error_count": 1, "navigation_error_count": 0},
            "download": {"rows": 6, "json_download": True},
            "empty_invalid": {"empty_ok": False, "invalid_ok": True},
        },
        "checks": [
            {"id": "ui.labels-landmark", "passed": True},
            {"id": "ui.search-filter-sort", "passed": False},
            {"id": "ui.keyboard-detail", "passed": False},
            {"id": "ui.visible-focus", "passed": True},
            {"id": "ui.responsive", "passed": True},
            {"id": "ui.download", "passed": False},
            {"id": "ui.empty-invalid", "passed": False},
        ],
    }), encoding="utf-8")
    components = _machine_components()
    next(x for x in components if x["dimension"] == "hidden_functional")["earned_points"] = 39
    next(x for x in components if x["dimension"] == "engineering_quality")["earned_points"] = 8
    contract_path = tmp_path / "contract.json"
    contract = _contract(contract_path)
    score = score_end_to_end_product(
        worktree=worktree,
        stage=stage,
        machine_components=components,
        contract=contract,
        contract_path=contract_path,
    )
    assert score["score"] == 79
