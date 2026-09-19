from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

NUMERIC_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "provider_total_tokens",
    "retry_count",
    "provider_billed_cost",
    "local_estimated_cost",
    "subscription_allocated_cost",
    "provider_elapsed_seconds",
    "first_output_latency_seconds",
)

ALIASES = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "cached_input_tokens": ("cached_input_tokens", "cache_read_input_tokens", "cache_read_tokens"),
    "cache_write_input_tokens": ("cache_write_input_tokens", "cache_creation_input_tokens", "cache_creation_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
    "provider_total_tokens": ("provider_total_tokens", "total_tokens"),
    "retry_count": ("retry_count", "retries"),
    "provider_elapsed_seconds": ("provider_elapsed_seconds", "duration_api_ms", "duration_api_seconds"),
    "first_output_latency_seconds": ("first_output_latency_seconds", "time_to_first_token_seconds"),
}


def _number(value: object) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _first_number(value: Mapping[str, Any], names: Iterable[str]) -> int | float | None:
    for name in names:
        observed = _number(value.get(name))
        if observed is not None:
            if name == "duration_api_ms":
                return float(observed) / 1000.0
            return observed
    return None


def empty_usage(
    *, currency: str | None, price_catalog_id: str | None, billing_mode: str = "unknown"
) -> dict[str, Any]:
    result = {field: None for field in NUMERIC_FIELDS}
    result.update(
        currency=currency,
        price_catalog_id=price_catalog_id,
        billing_mode=billing_mode,
        provider_billed_cost_semantics="unknown",
        local_estimated_cost_source="unavailable",
        token_evidence_complete=False,
        cost_evidence_complete=False,
        source="unavailable",
    )
    return result


def _estimate_cost(tokens: Mapping[str, Any], pricing: Mapping[str, Any] | None) -> float | None:
    if not isinstance(pricing, Mapping):
        return None
    rates = pricing.get("usd_per_million_tokens")
    if not isinstance(rates, Mapping):
        return None
    input_tokens = _number(tokens.get("input_tokens"))
    output_tokens = _number(tokens.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    cached = _number(tokens.get("cached_input_tokens")) or 0
    cache_write = _number(tokens.get("cache_write_input_tokens")) or 0
    reasoning = _number(tokens.get("reasoning_output_tokens")) or 0
    noncached = input_tokens
    if pricing.get("input_tokens_include_cached", True):
        noncached = max(0, input_tokens - cached - cache_write)
    total = 0.0
    components = (
        (noncached, rates.get("input")),
        (cached, rates.get("cached_input", rates.get("input"))),
        (cache_write, rates.get("cache_write_input", rates.get("input"))),
        (output_tokens, rates.get("output")),
        (reasoning, rates.get("reasoning_output", 0)),
    )
    for count, rate in components:
        if count and _number(rate) is None:
            return None
        total += float(count) * float(rate or 0) / 1_000_000.0
    return round(total, 8)


def normalize_usage(
    value: Mapping[str, Any],
    *,
    currency: str | None,
    price_catalog_id: str | None,
    source: str,
    billing: Mapping[str, Any] | None = None,
    pricing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    billing = billing or {}
    billing_mode = str(billing.get("mode", "unknown"))
    result = {field: None for field in NUMERIC_FIELDS}
    for field, aliases in ALIASES.items():
        result[field] = _first_number(value, aliases)
    if result["provider_total_tokens"] is None:
        input_tokens = result["input_tokens"]
        output_tokens = result["output_tokens"]
        if input_tokens is not None and output_tokens is not None:
            result["provider_total_tokens"] = input_tokens + output_tokens

    emitted_cost = _first_number(
        value,
        ("provider_billed_cost", "total_cost_usd", "cost_usd", "cost"),
    )
    explicit_local_cost = _number(value.get("local_estimated_cost"))
    catalog_cost = _estimate_cost(result, pricing)
    semantics = str(billing.get("provider_billed_cost_semantics", "unknown"))
    if billing_mode == "subscription":
        # Subscription usage has no attributable provider invoice line item.
        # Never copy a CLI-emitted cost into provider_billed_cost. Prefer a
        # pinned local catalog, then retain a provider-emitted equivalent only
        # as an explicitly labeled estimate when no catalog is configured.
        result["provider_billed_cost"] = None
        if explicit_local_cost is not None:
            local_cost = explicit_local_cost
            local_source = "explicit-local"
        elif catalog_cost is not None:
            local_cost = catalog_cost
            local_source = "price-catalog"
        elif emitted_cost is not None:
            local_cost = emitted_cost
            local_source = "provider-emitted-equivalent"
        else:
            local_cost = None
            local_source = "unavailable"
    else:
        result["provider_billed_cost"] = emitted_cost
        if explicit_local_cost is not None:
            local_cost = explicit_local_cost
            local_source = "explicit-local"
        elif catalog_cost is not None:
            local_cost = catalog_cost
            local_source = "price-catalog"
        else:
            local_cost = None
            local_source = "unavailable"
    result["local_estimated_cost"] = local_cost
    result["local_estimated_cost_source"] = local_source
    result["subscription_allocated_cost"] = _number(value.get("subscription_allocated_cost"))
    result["currency"] = value.get("currency") or currency
    result["price_catalog_id"] = value.get("price_catalog_id") or price_catalog_id
    result["billing_mode"] = billing_mode
    result["provider_billed_cost_semantics"] = semantics
    result["token_evidence_complete"] = all(
        result[field] is not None
        for field in ("input_tokens", "output_tokens", "provider_total_tokens")
    )
    if billing_mode == "subscription" and semantics == "not-attributable":
        result["cost_evidence_complete"] = result["local_estimated_cost"] is not None
    elif billing_mode == "synthetic":
        result["cost_evidence_complete"] = result["provider_billed_cost"] is not None
    else:
        result["cost_evidence_complete"] = (
            result["provider_billed_cost"] is not None or result["local_estimated_cost"] is not None
        )
    result["source"] = source
    return result


def _find_usage(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        keys = set(value)
        recognized = set(NUMERIC_FIELDS) | {alias for aliases in ALIASES.values() for alias in aliases} | {
            "total_cost_usd",
            "cost_usd",
        }
        if keys & recognized:
            return value
        for key in ("usage", "metrics", "token_usage", "provider_usage", "result"):
            nested = value.get(key)
            found = _find_usage(nested)
            if found is not None:
                return found
        for nested in value.values():
            found = _find_usage(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in reversed(value):
            found = _find_usage(nested)
            if found is not None:
                return found
    return None


def load_usage(
    usage_file: Path,
    stdout: str,
    *,
    currency: str | None,
    price_catalog_id: str | None,
    billing: Mapping[str, Any] | None = None,
    pricing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if usage_file.is_file():
        try:
            value = json.loads(usage_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            found = _find_usage(value) or value
            return normalize_usage(
                found,
                currency=currency,
                price_catalog_id=price_catalog_id,
                source="usage-file",
                billing=billing,
                pricing=pricing,
            )
    candidates: list[Any] = []
    for line in stdout.splitlines():
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    found = _find_usage(candidates)
    if found is not None:
        return normalize_usage(
            found,
            currency=currency,
            price_catalog_id=price_catalog_id,
            source="stdout-jsonl",
            billing=billing,
            pricing=pricing,
        )
    return empty_usage(
        currency=currency,
        price_catalog_id=price_catalog_id,
        billing_mode=str((billing or {}).get("mode", "unknown")),
    )


def sum_nullable(values: Iterable[int | float | None]) -> int | float | None:
    items = list(values)
    if not items or any(item is None for item in items):
        return None
    total = sum(item for item in items if item is not None)
    return round(total, 8) if isinstance(total, float) else total


def aggregate_usage(
    values: list[Mapping[str, Any]], *, billing: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    result = {
        field: sum_nullable([_number(value.get(field)) for value in values])
        for field in NUMERIC_FIELDS
    }
    currencies = {value.get("currency") for value in values if value.get("currency") is not None}
    catalogs = {
        value.get("price_catalog_id")
        for value in values
        if value.get("price_catalog_id") is not None
    }
    billing_modes = {value.get("billing_mode") for value in values if value.get("billing_mode")}
    semantics = {
        value.get("provider_billed_cost_semantics")
        for value in values
        if value.get("provider_billed_cost_semantics")
    }
    result["currency"] = next(iter(currencies)) if len(currencies) == 1 else None
    result["price_catalog_id"] = next(iter(catalogs)) if len(catalogs) == 1 else None
    result["billing_mode"] = next(iter(billing_modes)) if len(billing_modes) == 1 else "mixed"
    result["provider_billed_cost_semantics"] = next(iter(semantics)) if len(semantics) == 1 else "mixed"
    local_sources = {
        value.get("local_estimated_cost_source")
        for value in values
        if value.get("local_estimated_cost_source")
    }
    result["local_estimated_cost_source"] = (
        next(iter(local_sources)) if len(local_sources) == 1 else "mixed" if local_sources else "unavailable"
    )
    result["token_evidence_complete"] = bool(values) and all(
        value.get("token_evidence_complete") is True for value in values
    )
    result["cost_evidence_complete"] = bool(values) and all(
        value.get("cost_evidence_complete") is True for value in values
    )
    allocation = (billing or {}).get("subscription_allocation", {})
    if result["billing_mode"] == "subscription" and isinstance(allocation, Mapping):
        if allocation.get("method") == "fixed-per-arm-run":
            result["subscription_allocated_cost"] = _number(allocation.get("amount"))
    result["complete"] = result["token_evidence_complete"]
    return result
