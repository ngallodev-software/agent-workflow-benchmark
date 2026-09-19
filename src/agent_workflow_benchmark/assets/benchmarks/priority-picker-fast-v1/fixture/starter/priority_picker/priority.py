from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class BacklogValidationError(ValueError):
    """The backlog violates the frozen Priority Picker contract."""


NUMERIC_FIELDS = ("impact", "urgency", "effort", "confidence", "risk")
REQUIRED_FIELDS = ("id", "title", *NUMERIC_FIELDS, "status", "description")
STATUSES = {"planned", "ready", "in_progress", "blocked"}
SORT_FIELDS = {"priority": "score", "impact": "impact", "urgency": "urgency", "effort": "effort", "confidence": "confidence", "risk": "risk", "title": "title", "status": "status"}


def _validated_number(item_id: str, field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BacklogValidationError(f"item {item_id!r}: {field} must be numeric")
    if not 1 <= value <= 5:
        raise BacklogValidationError(f"item {item_id!r}: {field} must be from 1 through 5")
    return float(value)


def calculate_priority(item: dict[str, Any]) -> float:
    return round(
        (
            2 * float(item["impact"])
            + 1.0 * float(item["urgency"])
            + float(item["confidence"])
            + 0.5 * float(item["risk"])
        )
        / max(float(item["effort"]), 1.0),
        4,
    )


def validate_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(items, (str, bytes, dict)):
        raise BacklogValidationError("backlog must be an iterable of item objects")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise BacklogValidationError(f"item at index {index} must be an object")
        missing = [field for field in REQUIRED_FIELDS if field not in raw]
        if missing:
            raise BacklogValidationError(f"item at index {index} is missing: {', '.join(missing)}")
        item_id = raw["id"]
        title = raw["title"]
        description = raw["description"]
        if not isinstance(item_id, str) or not item_id.strip():
            raise BacklogValidationError(f"item at index {index}: id must be a non-empty string")
        if item_id in seen:
            raise BacklogValidationError(f"duplicate item id: {item_id}")
        seen.add(item_id)
        if not isinstance(title, str) or not title.strip():
            raise BacklogValidationError(f"item {item_id!r}: title must be a non-empty string")
        if not isinstance(description, str):
            raise BacklogValidationError(f"item {item_id!r}: description must be a string")
        if raw["status"] not in STATUSES:
            raise BacklogValidationError(f"item {item_id!r}: unsupported status {raw['status']!r}")
        item = dict(raw)
        item["id"] = item_id.strip()
        item["title"] = title.strip()
        for field in NUMERIC_FIELDS:
            numeric = _validated_number(item_id, field, raw[field])
            item[field] = int(numeric) if numeric.is_integer() else numeric
        item["score"] = calculate_priority(item)
        normalized.append(item)
    return normalized


def rank_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        validate_items(items),
        key=lambda item: (-item["score"], -item["urgency"], -item["impact"], item["id"]),
    )


def filter_items(items: Iterable[dict[str, Any]], query: str = "", status: str = "all", risk: str = "all") -> list[dict[str, Any]]:
    if status != "all" and status not in STATUSES:
        raise BacklogValidationError(f"unsupported status filter: {status}")
    if risk != "all" and str(risk) not in {"1", "2", "3", "4", "5"}:
        raise BacklogValidationError(f"unsupported risk filter: {risk}")
    needle = query.casefold().strip()
    return [
        item
        for item in rank_items(items)
        if (not needle or needle in item["title"].casefold() or needle in item["id"].casefold())
        and (status == "all" or item["status"] == status)
        and (risk == "all" or str(item["risk"]) == str(risk))
    ]


def sort_items(items: Iterable[dict[str, Any]], key: str = "priority", direction: str = "desc") -> list[dict[str, Any]]:
    if key not in SORT_FIELDS:
        raise BacklogValidationError(f"unsupported sort field: {key}")
    if direction not in {"asc", "desc"}:
        direction = "desc"  # benchmark defect: must reject
    values = rank_items(items)
    field = SORT_FIELDS[key]
    if key == "priority" and direction == "desc":
        return values
    reverse = direction == "desc"
    return sorted(values, key=lambda item: (item[field], item["id"]), reverse=reverse)


def export_ordering(items: Iterable[dict[str, Any]], destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"rank": rank, **item}
        for rank, item in enumerate(rank_items(items), start=1)
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_backlog(path: str | Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BacklogValidationError(f"backlog is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, list):
        raise BacklogValidationError("backlog root must be a JSON array")
    return validate_items(value)
