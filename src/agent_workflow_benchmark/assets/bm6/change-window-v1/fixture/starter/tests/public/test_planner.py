from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from change_window.planner import (
    ChangeWindowValidationError,
    build_change_plan,
    dependency_closure,
    estimate_minutes,
    load_change_set,
    plan_waves,
    validate_change_set,
)


def sample() -> dict:
    return {
        "window": {"duration_minutes": 80, "parallelism": 2},
        "services": [
            {
                "id": "db",
                "name": "Database",
                "owner": "data",
                "duration_minutes": 20,
                "risk": "low",
                "status": "ready",
                "dependencies": [],
            },
            {
                "id": "auth",
                "name": "Auth",
                "owner": "platform",
                "duration_minutes": 15,
                "risk": "medium",
                "status": "ready",
                "dependencies": ["db"],
            },
            {
                "id": "api",
                "name": "API",
                "owner": "platform",
                "duration_minutes": 30,
                "risk": "high",
                "status": "ready",
                "dependencies": ["auth"],
            },
            {
                "id": "worker",
                "name": "Worker",
                "owner": "platform",
                "duration_minutes": 15,
                "risk": "medium",
                "status": "ready",
                "dependencies": ["db"],
            },
        ],
    }


class ChangeWindowPlannerTests(unittest.TestCase):
    def test_validate_preserves_caller_data(self) -> None:
        value = sample()
        before = copy.deepcopy(value)
        result = validate_change_set(value)
        self.assertEqual(value, before)
        self.assertEqual(len(result["services"]), 4)

    def test_missing_dependency_is_rejected(self) -> None:
        value = sample()
        value["services"][2]["dependencies"] = ["missing"]
        with self.assertRaises(ChangeWindowValidationError):
            validate_change_set(value)

    def test_cycle_is_rejected(self) -> None:
        value = sample()
        value["services"][0]["dependencies"] = ["api"]
        with self.assertRaises(ChangeWindowValidationError):
            validate_change_set(value)

    def test_dependency_closure_is_deterministic(self) -> None:
        services = sample()["services"]
        self.assertEqual(dependency_closure(services, "api"), ["db", "auth"])

    def test_selected_service_auto_includes_dependencies(self) -> None:
        services = sample()["services"]
        self.assertEqual(
            plan_waves(services, parallelism=2, selected_ids=["api"]),
            [["db"], ["auth"], ["api"]],
        )

    def test_parallel_wave_and_duration(self) -> None:
        services = sample()["services"]
        waves = plan_waves(
            services,
            parallelism=2,
            selected_ids=["api", "worker"],
        )
        self.assertEqual(waves, [["db"], ["auth", "worker"], ["api"]])
        self.assertEqual(estimate_minutes(services, waves), 65)

    def test_build_plan_reports_window_fit(self) -> None:
        result = build_change_plan(sample())
        self.assertEqual(result["estimated_minutes"], 65)
        self.assertEqual(result["window_minutes"], 80)
        self.assertTrue(result["within_window"])

    def test_load_change_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "change-set.json"
            path.write_text(json.dumps(sample()), encoding="utf-8")
            result = load_change_set(path)
        self.assertEqual(result["window"]["parallelism"], 2)


if __name__ == "__main__":
    unittest.main()
