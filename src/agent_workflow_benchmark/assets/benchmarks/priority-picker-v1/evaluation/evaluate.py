from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

Check = tuple[str, bool, str]


def outcome(checks: list[Check], maximum: float) -> dict[str, Any]:
    passed = sum(1 for _, state, _ in checks if state)
    earned = round(maximum * passed / len(checks), 4) if checks else 0.0
    return {
        "state": "pass" if passed == len(checks) else ("partial" if passed else "fail"),
        "earned_points": earned,
        "checks": [
            {"id": id_, "passed": state, "detail": detail}
            for id_, state, detail in checks
        ],
        "details": [f"{passed}/{len(checks)} checks passed"],
    }


def load_priority(worktree: Path):
    sys.path.insert(0, str(worktree))
    for name in list(sys.modules):
        if name == "priority_picker" or name.startswith("priority_picker."):
            del sys.modules[name]
    return importlib.import_module("priority_picker.priority")


def item(id_: str = "A", **changes: Any) -> dict[str, Any]:
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


def try_check(id_: str, operation: Callable[[], bool], detail: str) -> Check:
    try:
        return id_, bool(operation()), detail
    except Exception as exc:  # evaluation records failures rather than aborting
        return id_, False, f"{detail}: {type(exc).__name__}: {exc}"


def hidden_functional(worktree: Path) -> list[Check]:
    module = load_priority(worktree)
    checks: list[Check] = []
    checks.append(try_check("formula", lambda: module.calculate_priority(item()) == 10.0, "exact frozen formula"))
    checks.append(try_check("tie-break", lambda: [x["id"] for x in module.rank_items([item("B"), item("A")])] == ["A", "B"], "score/urgency/impact/id ordering"))
    checks.append(try_check("score-attached", lambda: module.rank_items([item()])[0]["score"] == 10.0, "ranked records expose score"))
    checks.append(try_check("search", lambda: [x["id"] for x in module.filter_items([item("A", title="Needle"), item("B")], query="needle")] == ["A"], "case-insensitive search"))
    checks.append(try_check("status", lambda: [x["id"] for x in module.filter_items([item("A", status="blocked"), item("B")], status="blocked")] == ["A"], "status filtering"))
    checks.append(try_check("risk", lambda: [x["id"] for x in module.filter_items([item("A", risk=5), item("B", risk=2)], risk="5")] == ["A"], "risk filtering"))
    checks.append(try_check("sort", lambda: [x["id"] for x in module.sort_items([item("B", title="Zulu"), item("A", title="Alpha")], key="title", direction="asc")] == ["A", "B"], "alternate sorting"))
    def export_ok() -> bool:
        with tempfile.TemporaryDirectory() as directory:
            path = module.export_ordering([item("B"), item("A")], Path(directory) / "out.json")
            value = json.loads(path.read_text(encoding="utf-8"))
            return [entry["id"] for entry in value] == ["A", "B"] and value[0].get("rank", 1) == 1
    checks.append(try_check("export", export_ok, "export preserves ranked ordering"))
    checks.append(try_check("load", lambda: len(module.load_backlog(worktree / "data" / "backlog.json")) == 6, "loads supplied fixture"))
    return checks


def public_regression(worktree: Path) -> list[Check]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/public", "-v"],
        cwd=worktree,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return [("public-tests", result.returncode == 0, (result.stderr or result.stdout)[-2000:])]


def robustness(worktree: Path) -> list[Check]:
    module = load_priority(worktree)
    checks = [
        try_check("empty", lambda: module.rank_items([]) == [], "empty input is valid"),
        try_check("duplicate", lambda: _raises(module.BacklogValidationError, lambda: module.validate_items([item("A"), item("A")])), "duplicate IDs rejected"),
        try_check("boolean", lambda: _raises(module.BacklogValidationError, lambda: module.validate_items([item(impact=True)])), "booleans rejected as numeric factors"),
        try_check("malformed-root", lambda: _raises(module.BacklogValidationError, lambda: module.validate_items("not-items")), "non-list-like roots rejected"),
    ]
    def scale() -> bool:
        values = [item(f"I-{index:04d}", impact=(index % 5) + 1, urgency=((index + 1) % 5) + 1) for index in range(1000)]
        started = time.monotonic()
        ranked = module.rank_items(values)
        return len(ranked) == 1000 and time.monotonic() - started < 2.0
    checks.append(try_check("scale", scale, "1,000 items rank within two seconds"))
    return checks


def _raises(error: type[BaseException], operation: Callable[[], Any]) -> bool:
    try:
        operation()
    except error:
        return True
    return False


def accessibility(stage_dir: Path) -> list[Check]:
    path = stage_dir / "visual" / "assessment.json"
    if not path.is_file():
        return [(id_, False, "visual assessment missing") for id_ in ("runtime", "labels", "keyboard", "responsive", "console")]
    value = json.loads(path.read_text(encoding="utf-8"))
    checks = {str(item["id"]): bool(item["passed"]) for item in value.get("checks", [])}
    groups = {
        "runtime": ["runtime-match", "app-loaded"],
        "labels": ["controls-labeled", "main-landmark"],
        "keyboard": ["keyboard-detail", "focus-visible"],
        "responsive": ["desktop-no-overflow", "tablet-no-overflow", "mobile-no-overflow"],
        "console": ["no-console-errors", "export-control"],
    }
    return [
        (group, all(checks.get(name, False) for name in names), f"required checks: {', '.join(names)}")
        for group, names in groups.items()
    ]


def scope_completeness(worktree: Path) -> list[Check]:
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
    return [
        ("required-files", all(path.is_file() for path in required), "required source and web files exist"),
        ("plan", plan.is_file() and len(plan.read_text(encoding="utf-8")) > 80, "phase plan retained"),
        ("readme", readme.is_file() and "score" in readme.read_text(encoding="utf-8").lower(), "README documents scoring and operation"),
        ("immutable-input", data.is_file() and len(json.loads(data.read_text(encoding="utf-8"))) == 6, "supplied fixture retained"),
        ("no-dependencies", not any((worktree / name).exists() for name in ("package.json", "requirements.txt", "Pipfile", "poetry.lock", "node_modules")), "no external dependency surface"),
    ]


def engineering(worktree: Path) -> list[Check]:
    compile_result = subprocess.run([sys.executable, "-m", "compileall", "-q", "priority_picker", "tests"], cwd=worktree, check=False, capture_output=True, text=True)
    tests = public_regression(worktree)[0]
    source_files = list((worktree / "priority_picker").rglob("*.py")) + list((worktree / "priority_picker" / "web").glob("*"))
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in source_files if path.is_file())
    readme = (worktree / "README.md").read_text(encoding="utf-8", errors="replace") if (worktree / "README.md").is_file() else ""
    plan = (worktree / "BENCHMARK_PLAN.md").read_text(encoding="utf-8", errors="replace") if (worktree / "BENCHMARK_PLAN.md").is_file() else ""
    return [
        ("compile", compile_result.returncode == 0, compile_result.stderr[-1000:]),
        ("tests", tests[1], tests[2]),
        ("no-stubs", "NotImplementedError" not in source and "TODO" not in source.upper(), "no implementation stubs remain"),
        ("formula-doc", "2*impact" in readme.replace(" ", "") or "2 * impact" in readme, "README states the frozen formula"),
        ("verification-plan", "verify" in plan.lower() and "non-target" in plan.lower(), "plan records verification and non-targets"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--max-points", type=float, required=True)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    functions = {
        "hidden_functional": lambda: hidden_functional(worktree),
        "public_regression": lambda: public_regression(worktree),
        "robustness": lambda: robustness(worktree),
        "accessibility_ui": lambda: accessibility((args.stage_dir or worktree).resolve()),
        "scope_completeness": lambda: scope_completeness(worktree),
        "engineering_quality": lambda: engineering(worktree),
    }
    if args.dimension not in functions:
        raise SystemExit(f"unsupported dimension: {args.dimension}")
    try:
        result = outcome(functions[args.dimension](), args.max_points)
    except Exception as exc:
        result = {"state": "harness_failure", "earned_points": 0.0, "checks": [], "details": [f"{type(exc).__name__}: {exc}"]}
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
