from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping


Check = dict[str, Any]


def _contract(path: Path, dimension: str) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    for item in value["dimensions"]:
        if item["id"] == dimension:
            return value, {str(check["id"]): check for check in item["checks"]}
    raise RuntimeError(f"contract has no dimension {dimension}")


def _check(definitions: Mapping[str, Mapping[str, Any]], id_: str, operation: Callable[[], bool], detail: str) -> Check:
    definition = definitions[id_]
    try:
        passed = bool(operation())
        observed = detail
    except Exception as exc:  # Solution failures become check failures, not harness failures.
        passed = False
        observed = f"{detail}: {type(exc).__name__}: {exc}"
    maximum = float(definition["max_points"])
    return {
        "id": id_,
        "passed": passed,
        "earned_points": maximum if passed else 0.0,
        "evidence_reference": definition["evidence_reference"],
        "detail": observed,
    }


def _failure_checks(definitions: Mapping[str, Mapping[str, Any]], exc: Exception) -> list[Check]:
    return [
        {
            "id": id_,
            "passed": False,
            "earned_points": 0.0,
            "evidence_reference": definition["evidence_reference"],
            "detail": f"evaluator caught solution failure: {type(exc).__name__}: {exc}",
        }
        for id_, definition in definitions.items()
    ]


def _outcome(checks: list[Check], maximum: float) -> dict[str, Any]:
    earned = round(sum(float(item["earned_points"]) for item in checks), 4)
    return {
        "state": "pass" if earned == maximum else ("partial" if earned else "fail"),
        "earned_points": earned,
        "checks": checks,
        "details": [f"{sum(1 for item in checks if item['passed'])}/{len(checks)} contracted checks passed"],
    }


def _load_priority(worktree: Path):
    sys.path.insert(0, str(worktree))
    for name in list(sys.modules):
        if name == "priority_picker" or name.startswith("priority_picker."):
            del sys.modules[name]
    return importlib.import_module("priority_picker.priority")


def _item(id_: str = "A", **changes: Any) -> dict[str, Any]:
    value = {
        "id": id_,
        "title": f"Item {id_}",
        "impact": 5,
        "urgency": 4,
        "effort": 2,
        "confidence": 3,
        "risk": 2,
        "status": "ready",
        "description": f"Description {id_}",
    }
    value.update(changes)
    return value


def _raises(error: type[BaseException], operation: Callable[[], Any]) -> bool:
    try:
        operation()
    except error:
        return True
    return False


def hidden_functional(worktree: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    module = _load_priority(worktree)
    checks: list[Check] = []
    checks.append(_check(definitions, "hidden.formula.integer", lambda: module.calculate_priority(_item()) == 10.0, "integer formula equals 10.0"))
    checks.append(_check(definitions, "hidden.formula.decimal-rounding", lambda: module.calculate_priority(_item(impact=4.5, urgency=3.25, effort=2.5, confidence=4.25, risk=1.5)) == 7.55, "decimal formula is rounded to four places"))
    checks.append(_check(definitions, "hidden.formula.effort-floor", lambda: module.calculate_priority(_item(effort=0)) == 20.0, "calculate_priority floors effort at one"))
    checks.append(_check(definitions, "hidden.tie.score", lambda: [x["id"] for x in module.rank_items([_item("L", impact=1), _item("H", impact=5)])] == ["H", "L"], "score descending is primary"))
    checks.append(_check(definitions, "hidden.tie.urgency", lambda: [x["id"] for x in module.rank_items([_item("L", impact=5, urgency=3), _item("H", impact=3.5, urgency=5)])] == ["H", "L"], "equal scores use urgency descending"))
    checks.append(_check(definitions, "hidden.tie.impact", lambda: [x["id"] for x in module.rank_items([_item("L", impact=4, confidence=3), _item("H", impact=5, confidence=1)])] == ["H", "L"], "equal score/urgency uses impact descending"))
    checks.append(_check(definitions, "hidden.tie.id", lambda: [x["id"] for x in module.rank_items([_item("B"), _item("A")])] == ["A", "B"], "final tie uses ID ascending"))

    def ranked_schema() -> bool:
        source = [_item("B"), _item("A")]
        before = copy.deepcopy(source)
        ranked = module.rank_items(source)
        return source == before and [x["id"] for x in ranked] == ["A", "B"] and all("score" in x for x in ranked)

    checks.append(_check(definitions, "hidden.ranked-schema", ranked_schema, "ranked records expose scores without mutating input"))
    checks.append(_check(definitions, "hidden.search.title", lambda: [x["id"] for x in module.filter_items([_item("A", title="Needle"), _item("B")], query="needle")] == ["A"], "title search is case-insensitive"))
    checks.append(_check(definitions, "hidden.search.description", lambda: [x["id"] for x in module.filter_items([_item("A", description="Hidden Needle"), _item("B")], query="NEEDLE")] == ["A"], "description search is case-insensitive"))
    checks.append(_check(definitions, "hidden.filters.combined", lambda: [x["id"] for x in module.filter_items([_item("A", title="Needle", status="blocked", risk=5), _item("B", title="Needle", status="ready", risk=5), _item("C", title="Other", status="blocked", risk=5)], query="needle", status="blocked", risk="5")] == ["A"], "query/status/risk compose"))

    def supported_sorts() -> bool:
        values = [_item("B", title="Zulu", risk=1), _item("A", title="Alpha", risk=5)]
        return (
            [x["id"] for x in module.sort_items(values, key="title", direction="asc")] == ["A", "B"]
            and [x["id"] for x in module.sort_items(values, key="risk", direction="desc")] == ["A", "B"]
        )

    checks.append(_check(definitions, "hidden.sort.supported", supported_sorts, "supported keys and directions sort deterministically"))
    checks.append(_check(definitions, "hidden.sort.invalid", lambda: _raises(module.BacklogValidationError, lambda: module.sort_items([_item()], key="unknown")) and _raises(module.BacklogValidationError, lambda: module.sort_items([_item()], direction="sideways")), "invalid sort key/direction rejected"))

    def export_ok() -> bool:
        with tempfile.TemporaryDirectory() as directory:
            path = module.export_ordering([_item("B"), _item("A")], Path(directory) / "out.json")
            value = json.loads(path.read_text(encoding="utf-8"))
            return [entry["id"] for entry in value] == ["A", "B"] and [entry.get("rank") for entry in value] == [1, 2]

    checks.append(_check(definitions, "hidden.export", export_ok, "export contains deterministic order and ranks"))
    checks.append(_check(definitions, "hidden.load", lambda: len(module.load_backlog(worktree / "data" / "backlog.json")) == 6, "supplied fixture loads and validates"))

    def deterministic() -> bool:
        source = [_item("B"), _item("A")]
        before = copy.deepcopy(source)
        first = module.rank_items(source)
        second = module.rank_items(source)
        return first == second and source == before

    checks.append(_check(definitions, "hidden.determinism", deterministic, "repeatable operations do not mutate caller data"))
    return checks


def _run_public(worktree: Path, test_name: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "tests/public/test_priority.py", f"PriorityTests.{test_name}", "-v"],
        cwd=worktree,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        env={**os.environ, "PYTHONPATH": str(worktree)},
    )
    return result.returncode == 0, (result.stderr or result.stdout)[-2000:]


def public_regression(worktree: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    mapping = [
        ("public.formula", "test_frozen_formula"),
        ("public.ranking", "test_ranking_uses_frozen_tie_breakers"),
        ("public.validation", "test_malformed_range_is_rejected"),
        ("public.filter-sort", "test_filter_and_sort"),
        ("public.export-server", "test_export_and_server_contract"),
    ]
    checks: list[Check] = []
    for id_, name in mapping:
        passed, detail = _run_public(worktree, name)
        checks.append(_check(definitions, id_, lambda passed=passed: passed, detail))
    return checks


def robustness(worktree: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    module = _load_priority(worktree)
    checks: list[Check] = []
    checks.append(_check(definitions, "robust.required-fields", lambda: _raises(module.BacklogValidationError, lambda: module.validate_items([{k: v for k, v in _item().items() if k != "title"}])), "missing fields rejected"))

    def type_range_status() -> bool:
        bad = [
            _item(impact=True), _item(urgency="5"), _item(effort=0), _item(confidence=6),
            _item(status="unknown"), _item(id_=1), _item(title=""), _item(description=3),
        ]
        return all(_raises(module.BacklogValidationError, lambda value=value: module.validate_items([value])) for value in bad)

    checks.append(_check(definitions, "robust.types-ranges-status", type_range_status, "types/ranges/statuses/booleans rejected"))
    checks.append(_check(definitions, "robust.empty-duplicate", lambda: module.rank_items([]) == [] and _raises(module.BacklogValidationError, lambda: module.validate_items([_item("A"), _item("A")])), "empty accepted and duplicates rejected"))

    def malformed_load() -> bool:
        root_rejected = _raises(module.BacklogValidationError, lambda: module.validate_items("not-items"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            invalid_json = _raises(module.BacklogValidationError, lambda: module.load_backlog(path))
        return root_rejected and invalid_json

    checks.append(_check(definitions, "robust.malformed-load", malformed_load, "malformed roots and JSON rejected usefully"))

    def scale() -> bool:
        values = [_item(f"I-{index:04d}", impact=(index % 5) + 1, urgency=((index + 1) % 5) + 1) for index in range(1000)]
        started = time.monotonic()
        ranked = module.rank_items(values)
        return len(ranked) == 1000 and time.monotonic() - started < 2.0

    checks.append(_check(definitions, "robust.scale", scale, "one thousand items rank within two seconds"))
    return checks


def accessibility(stage_dir: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    path = stage_dir / "visual" / "assessment.json"
    if not path.is_file():
        return [_check(definitions, id_, lambda: False, "visual assessment missing") for id_ in definitions]
    value = json.loads(path.read_text(encoding="utf-8"))
    observed = {str(item["id"]): item for item in value.get("checks", [])}
    return [
        _check(
            definitions,
            id_,
            lambda id_=id_: bool(observed.get(id_, {}).get("passed")),
            str(observed.get(id_, {}).get("detail", "visual check missing")),
        )
        for id_ in definitions
    ]


def scope_completeness(worktree: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    required = [
        worktree / "priority_picker" / "priority.py",
        worktree / "priority_picker" / "server.py",
        worktree / "priority_picker" / "web" / "index.html",
        worktree / "priority_picker" / "web" / "styles.css",
        worktree / "priority_picker" / "web" / "app.js",
    ]
    plan = worktree / "BENCHMARK_PLAN.md"
    readme = worktree / "README.md"
    data = worktree / "data" / "backlog.json"
    checks = [
        _check(definitions, "scope.required-files", lambda: all(path.is_file() for path in required), "required Python and web files exist"),
        _check(definitions, "scope.plan", lambda: plan.is_file() and len(plan.read_text(encoding="utf-8")) > 80, "phase plan retained"),
        _check(definitions, "scope.readme", lambda: readme.is_file() and all(term in readme.read_text(encoding="utf-8").lower() for term in ("score", "run", "test")), "README documents scoring, operation and tests"),
        _check(definitions, "scope.immutable-input", lambda: data.is_file() and len(json.loads(data.read_text(encoding="utf-8"))) == 6, "supplied fixture retained"),
        _check(definitions, "scope.no-dependencies", lambda: not any((worktree / name).exists() for name in ("package.json", "requirements.txt", "Pipfile", "poetry.lock", "node_modules")), "no external dependency surface"),
    ]
    return checks


def engineering(worktree: Path, definitions: Mapping[str, Mapping[str, Any]]) -> list[Check]:
    compile_result = subprocess.run([sys.executable, "-m", "compileall", "-q", "priority_picker", "tests"], cwd=worktree, check=False, capture_output=True, text=True)
    source_files = list((worktree / "priority_picker").rglob("*.py")) + list((worktree / "priority_picker" / "web").glob("*"))
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in source_files if path.is_file())
    readme = (worktree / "README.md").read_text(encoding="utf-8", errors="replace") if (worktree / "README.md").is_file() else ""
    plan = (worktree / "BENCHMARK_PLAN.md").read_text(encoding="utf-8", errors="replace") if (worktree / "BENCHMARK_PLAN.md").is_file() else ""
    normalized = readme.replace(" ", "").lower()
    return [
        _check(definitions, "quality.compile", lambda: compile_result.returncode == 0, compile_result.stderr[-1000:]),
        _check(
            definitions,
            "quality.no-stubs",
            lambda: re.search(r"\braise\s+NotImplementedError\b|\bTODO\b", source, flags=re.IGNORECASE) is None,
            "no implementation stubs remain",
        ),
        _check(definitions, "quality.formula-doc", lambda: "2*impact" in normalized and "urgency" in readme.lower() and "tie" in readme.lower(), "formula and tie breakers documented"),
        _check(definitions, "quality.verification-plan", lambda: "verify" in plan.lower() and "non-target" in plan.lower(), "plan records verification and non-targets"),
        _check(definitions, "quality.deterministic-design", lambda: len(source) < 120_000 and not any(term in source for term in ("requests.", "fetch('http://", 'fetch("http://')), "implementation remains bounded and has no undeclared network client"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--max-points", type=float, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    _value, definitions = _contract(args.contract, args.dimension)
    expected_maximum = sum(float(item["max_points"]) for item in definitions.values())
    if abs(expected_maximum - args.max_points) > 1e-9:
        raise RuntimeError(f"contract/scorer maximum mismatch: {expected_maximum} != {args.max_points}")
    try:
        if args.dimension == "hidden_functional":
            checks = hidden_functional(args.worktree, definitions)
        elif args.dimension == "public_regression":
            checks = public_regression(args.worktree, definitions)
        elif args.dimension == "robustness":
            checks = robustness(args.worktree, definitions)
        elif args.dimension == "accessibility_ui":
            if args.stage_dir is None:
                raise RuntimeError("accessibility scorer requires --stage-dir")
            checks = accessibility(args.stage_dir, definitions)
        elif args.dimension == "scope_completeness":
            checks = scope_completeness(args.worktree, definitions)
        elif args.dimension == "engineering_quality":
            checks = engineering(args.worktree, definitions)
        else:
            raise RuntimeError(f"unknown dimension {args.dimension}")
    except Exception as exc:
        checks = _failure_checks(definitions, exc)
    result = _outcome(checks, args.max_points)
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
