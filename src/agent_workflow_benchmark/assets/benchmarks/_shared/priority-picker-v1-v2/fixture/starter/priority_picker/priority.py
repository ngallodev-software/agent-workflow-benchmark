from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class BacklogValidationError(ValueError):
    """Raised when the supplied backlog does not match the frozen contract."""


def calculate_priority(item: dict[str, Any]) -> float:
    raise NotImplementedError("implement the frozen priority formula")


def validate_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    raise NotImplementedError("validate and normalize backlog items")


def rank_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    raise NotImplementedError("return backlog items in deterministic priority order")


def filter_items(
    items: Iterable[dict[str, Any]],
    query: str = "",
    status: str = "all",
    risk: str = "all",
) -> list[dict[str, Any]]:
    raise NotImplementedError("filter backlog items")


def sort_items(
    items: Iterable[dict[str, Any]], key: str = "priority", direction: str = "desc"
) -> list[dict[str, Any]]:
    raise NotImplementedError("sort backlog items")


def export_ordering(items: Iterable[dict[str, Any]], destination: str | Path) -> Path:
    raise NotImplementedError("export the current ordering")


def load_backlog(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise BacklogValidationError("backlog root must be a JSON array")
    return validate_items(value)
