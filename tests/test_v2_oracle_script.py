from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2_ORACLE = ROOT / "scripts" / "adjudication" / "v2-oracle.sh"
P0B_PREPARE = ROOT / "scripts" / "adjudication" / "p0b-prepare-resolutions.sh"


def test_v2_oracle_driver_is_versioned_and_fail_closed():
    text = V2_ORACLE.read_text(encoding="utf-8")

    assert 'STUDY="routing-semantic-v2"' in text
    assert 'MODEL="openai-api/codex-lb/deepseek-flash"' in text
    assert 'required = [f"IA-{n}" for n in range(1, 12)]' in text
    assert '--oracle-version routing-semantic-oracle-v2.0.0' in text
    assert text.count('--study "$STUDY"') >= 4
    assert 'V2_CAPTURE_CODEX_LB_INGRESS:-1' in text
    assert 'fmt.get("type") != "json_schema"' in text
    assert 'fmt.get("strict") is not True' in text
    assert 'schema_sha256' in text
    assert 'do not retry this real cohort in place' in text
    assert "routing-semantic-v1" not in text


def test_v2_oracle_driver_uses_separate_private_roots():
    text = V2_ORACLE.read_text(encoding="utf-8")

    assert "routing-semantic-v2-qualification" in text
    assert "routing-semantic-v2-oracle" in text
    assert 'ORACLE_RUN="${V2_ORACLE_RUN:-$ORACLE_ROOT/run-01}"' in text
    assert 'LOG_DIR="$ORACLE_ROOT/logs/$(basename "$ORACLE_RUN")"' in text
    assert 'DIAG_DIR="$ORACLE_ROOT/diagnostics/$(basename "$ORACLE_RUN")"' in text


def test_resolution_helper_keeps_v1_default_but_allows_versioned_override():
    text = P0B_PREPARE.read_text(encoding="utf-8")

    assert (
        '${FREEZE_RERUN_COMMAND:-bash scripts/adjudication/p0b-freeze.sh}'
        in text
    )
