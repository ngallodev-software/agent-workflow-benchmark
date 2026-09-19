from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class BacklogValidationError(ValueError):
    pass


FIELDS = ("impact", "urgency", "effort", "confidence", "risk")
STATUSES = {"planned", "ready", "in_progress", "blocked"}


def calculate_priority(item: dict[str, Any]) -> float:
    return round(
        (2 * float(item["impact"]) + 1.5 * float(item["urgency"]) + float(item["confidence"]) + 0.5 * float(item["risk"]))
        / max(float(item["effort"]), 1),
        4,
    )


def validate_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise BacklogValidationError("each backlog item must be an object")
        if not item.get("id") or not item.get("title"):
            raise BacklogValidationError("id and title are required")
        for field in FIELDS:
            value = item.get(field)
            if not isinstance(value, (int, float)) or not 1 <= value <= 5:
                raise BacklogValidationError(f"{field} must be from 1 through 5")
        if item.get("status") not in STATUSES:
            raise BacklogValidationError("invalid status")
        normalized = dict(item)
        normalized["score"] = calculate_priority(normalized)
        result.append(normalized)
    return result


def rank_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    values = validate_items(items)
    return sorted(values, key=lambda item: (-item["score"], -item["urgency"], -item["impact"], item["id"]))


def filter_items(items: Iterable[dict[str, Any]], query: str = "", status: str = "all", risk: str = "all") -> list[dict[str, Any]]:
    query = query.lower().strip()
    values = rank_items(items)
    return [
        item for item in values
        if (not query or query in item["title"].lower() or query in item.get("description", "").lower())
        and (status == "all" or item["status"] == status)
        and (risk == "all" or str(item["risk"]) == str(risk))
    ]


def sort_items(items: Iterable[dict[str, Any]], key: str = "priority", direction: str = "desc") -> list[dict[str, Any]]:
    values = rank_items(items)
    mapping = {"priority": "score", "impact": "impact", "urgency": "urgency", "effort": "effort", "risk": "risk", "title": "title"}
    field = mapping.get(key, "score")
    return sorted(values, key=lambda item: item[field], reverse=direction == "desc")


def export_ordering(items: Iterable[dict[str, Any]], destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(json.dumps(rank_items(items), indent=2) + "\n", encoding="utf-8")
    return path


def load_backlog(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise BacklogValidationError("backlog root must be a JSON array")
    return validate_items(value)
