#!/usr/bin/env python3
from __future__ import annotations

import json

import inspect_swe

from agent_workflow_benchmark.compat.inspect_swe_output_schema import (
    prepare_output_schema,
)


def main() -> int:
    good = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "case_id": {
                "type": "string",
                "enum": ["case-1"],
            }
        },
        "required": ["case_id"],
    }
    serialized = prepare_output_schema(good)
    assert serialized == json.dumps(good, sort_keys=True, separators=(",", ":"))

    # Construction succeeds. Do not execute the returned agent: this verification
    # is intentionally a zero-model-call construction test.
    inspect_swe.codex_cli(output_schema=good)

    bad = {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "case_id": {
                                    "const": "case-1",
                                }
                            },
                        }
                    ]
                },
            }
        },
    }
    expected_paths = {
        "/properties/records/minItems",
        "/properties/records/maxItems",
        "/properties/records/items/anyOf/0/properties/case_id/const",
    }
    try:
        inspect_swe.codex_cli(output_schema=bad)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("unsupported output schema was accepted")

    assert "active Inspect bridge cannot preserve" in message
    for path in expected_paths:
        assert path in message

    try:
        inspect_swe.codex_cli(
            output_schema={"type": "string", "enum": [{"not": {"json"}}]}
        )
    except ValueError as exc:
        assert "JSON serializable" in str(exc)
    else:
        raise AssertionError("non-serializable output schema was accepted")

    try:
        inspect_swe.codex_cli(output_schema=good, centaur=True)
    except ValueError as exc:
        assert "only supported for headless codex exec" in str(exc)
    else:
        raise AssertionError("centaur + output_schema was accepted")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
