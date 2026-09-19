from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from priority_picker.priority import (
    BacklogValidationError,
    calculate_priority,
    export_ordering,
    rank_items,
    validate_items,
)


ITEM = {
    "id": "A",
    "title": "Example",
    "impact": 5,
    "urgency": 4,
    "effort": 2,
    "confidence": 3,
    "risk": 2,
    "status": "ready",
    "description": "Example item",
}


class PriorityTests(unittest.TestCase):
    def test_frozen_formula(self) -> None:
        self.assertEqual(calculate_priority(dict(ITEM)), 10.0)

    def test_ranking_uses_frozen_tie_breakers(self) -> None:
        low_id = {**ITEM, "id": "A", "title": "A"}
        high_id = {**ITEM, "id": "B", "title": "B"}
        self.assertEqual([item["id"] for item in rank_items([high_id, low_id])], ["A", "B"])

    def test_malformed_range_is_rejected(self) -> None:
        with self.assertRaises(BacklogValidationError):
            validate_items([{**ITEM, "effort": 0}])

    def test_export_writes_ranked_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = export_ordering([ITEM], Path(directory) / "ordering.json")
            self.assertTrue(path.is_file())
            self.assertIn('"id": "A"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
