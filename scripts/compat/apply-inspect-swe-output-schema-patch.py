#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from agent_workflow_benchmark.compat.inspect_swe_output_schema import (
    InspectSweOutputSchemaPatchError,
    apply_installed_patch,
)


def main() -> int:
    try:
        info = apply_installed_patch()
    except InspectSweOutputSchemaPatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(info, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
