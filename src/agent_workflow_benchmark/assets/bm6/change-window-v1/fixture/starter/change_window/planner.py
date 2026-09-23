from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


class ChangeWindowValidationError(ValueError):
    """Raised when the change-window input violates the public contract."""


def validate_change_set(value: Any) -> dict[str, Any]:
    raise NotImplementedError


def dependency_closure(
    services: Iterable[dict[str, Any]],
    service_id: str,
) -> list[str]:
    raise NotImplementedError


def dependent_closure(
    services: Iterable[dict[str, Any]],
    service_id: str,
) -> list[str]:
    raise NotImplementedError


def plan_waves(
    services: Iterable[dict[str, Any]],
    *,
    parallelism: int,
    selected_ids: Iterable[str] | None = None,
) -> list[list[str]]:
    raise NotImplementedError


def estimate_minutes(
    services: Iterable[dict[str, Any]],
    waves: Iterable[Iterable[str]],
) -> int:
    raise NotImplementedError


def build_change_plan(
    value: Any,
    *,
    selected_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    raise NotImplementedError


def filter_services(
    services: Iterable[dict[str, Any]],
    *,
    query: str = "",
    owner: str = "all",
    risk: str = "all",
    status: str = "all",
) -> list[dict[str, Any]]:
    raise NotImplementedError


def load_change_set(path: str | Path) -> dict[str, Any]:
    raise NotImplementedError
