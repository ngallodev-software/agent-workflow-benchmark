from __future__ import annotations

import pytest

from agent_workflow_benchmark.compat.inspect_swe_output_schema import (
    InspectSweOutputSchemaPatchError,
    LEGACY_PATCH_MARKER,
    patch_source_text,
)


def test_legacy_output_schema_patch_requires_pristine_reinstall() -> None:
    source = f"before\n{LEGACY_PATCH_MARKER}\nafter\n"
    with pytest.raises(
        InspectSweOutputSchemaPatchError,
        match="restore pristine inspect-swe 0.2.71 bytes",
    ):
        patch_source_text(source)
