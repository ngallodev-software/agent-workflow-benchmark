# OpenSpec Change Bundle: Expose Codex Final-Output JSON Schema Through Inspect-SWE

**Change ID:** `expose-codex-output-schema`  
**Primary repository:** `meridianlabs-ai/inspect_swe`  
**Companion repository:** `UKGovernmentBEIS/inspect_ai`  
**Upstream feature request:** `meridianlabs-ai/inspect_swe#176`  
**Prepared against Inspect-SWE HEAD:** `d5bb1abdf59cd5cfdb7217667e500df3e83ece92`  
**Observed study runtime:** Inspect AI `0.3.268`, Inspect-SWE `0.2.71`, Codex CLI `0.158.0`

## Revision trigger

A live `routing-semantic-v2` qualification attempt reached the real bridged Codex/DeepSeek path and exposed a second-order structured-output failure.

The benchmark supplied a JSON Schema containing constraints that native Codex accepts but Inspect AI `0.3.268`'s Responses bridge does not model. The bridge warned that `const`, `minItems`, and `maxItems` would be dropped. The generated per-case schema used:

```json
{"case_id":{"const":"<case id>"}}
```

After `const` was dropped, the provider received an empty schema node for `case_id` and rejected the request with HTTP 400 because that node had no `type`.

No adjudication sample completed. The failed attempt is methodological evidence, not a contaminated experimental result.

This revises the earlier proposal. Transporting a caller-supplied schema into native Codex is not sufficient when the active Inspect bridge cannot faithfully preserve that schema.

## Repository scope decision

The production feature remains an **Inspect-SWE** change.

Inspect-SWE owns the new public `codex_cli(output_schema=...)` boundary and therefore MUST reject output schemas whose constraint semantics cannot survive the active Inspect bridge.

Inspect AI is not required to broaden its JSON Schema model as part of this PR. Its current behavior is useful evidence: `client_json_schema()` detects unmodelled constraint keywords, warns, and then validates through `inspect_ai.util._json.JSONSchema`, whose default Pydantic behavior drops unknown fields.

This PR MUST NOT silently compensate by rewriting unsupported constraints into different constraints. For example, it MUST NOT rewrite `{"const":"x"}` to `{"type":"string","enum":["x"]}`. Callers that need a bridge-representable schema are responsible for supplying one.

## Proposal

### Why

`inspect_swe.codex_cli()` can execute Codex through Inspect's sandbox bridge but does not expose Codex CLI's native final-output JSON Schema constraint.

Codex already supports `codex exec --output-schema <FILE>`. Evaluation systems that require a machine-contract final answer should be able to use that native enforcement while retaining Inspect bridging, accounting, transcripts, tools, retries, and downstream validation.

The live qualification failure adds one non-negotiable requirement: the public API must fail closed when the supplied schema contains constraint keywords that the active Inspect bridge cannot faithfully carry.

### What changes

- Add optional `output_schema` to `codex_cli()`.
- Validate the supplied schema synchronously during `codex_cli()` construction.
- Reject any non-annotative JSON Schema keyword that the active Inspect `JSONSchema` model does not represent, at any modeled nested schema position.
- Include the nested JSON Pointer path of every rejected keyword in the error.
- Perform this rejection before sandbox creation, Codex launch, bridge traffic, or any model call.
- Accept conservative bridge-representable schemas such as `{"type":"string","enum":["case-1"]}`.
- Do not rewrite, weaken, normalize, repair, or substitute caller schema semantics.
- Serialize a validated schema deterministically inside the selected sandbox.
- Pass the sandbox path to native Codex through `--output-schema`.
- Preserve current behavior when `output_schema` is omitted.
- Reject `output_schema` in Centaur mode.
- Preserve strict downstream validation as an independent boundary.

## Specification

### Requirement: Optional final-output JSON Schema

The Codex CLI agent SHALL accept an optional JSON object describing the required shape of the final unattended Codex response.

#### Scenario: Caller supplies a schema

- **GIVEN** a headless `codex_cli()` agent
- **AND** the caller supplies a bridge-representable final-output schema
- **WHEN** the agent executes
- **THEN** the schema SHALL be staged inside the selected sandbox
- **AND** Codex SHALL receive `--output-schema <sandbox-path>`
- **AND** the existing Inspect bridge SHALL remain active.

#### Scenario: Caller omits a schema

- **WHEN** `output_schema` is `None`
- **THEN** command construction and runtime behavior SHALL remain compatible with existing behavior
- **AND** no output-schema CLI option SHALL be emitted.

### Requirement: Fail closed on bridge-unrepresentable constraint semantics

Inspect-SWE SHALL reject an output schema if any non-annotative JSON Schema keyword would be dropped by the active Inspect response-schema bridge.

The check SHALL be based on the active Inspect `JSONSchema` model rather than an independently invented provider schema dialect.

Pure annotations that Inspect intentionally treats as non-constraining, such as `title`, `$schema`, `$id`, `$comment`, `deprecated`, `readOnly`, and `writeOnly`, MAY be ignored for this fail-closed constraint check.

#### Scenario: Nested `const` is unsupported

- **GIVEN** `output_schema` contains `/properties/records/items/anyOf/0/properties/case_id/const`
- **WHEN** `codex_cli()` is constructed
- **THEN** construction SHALL raise an actionable configuration error
- **AND** the error SHALL name `const`
- **AND** the error SHALL include the JSON Pointer path
- **AND** no sandbox, Codex process, bridge request, or model call SHALL occur.

#### Scenario: Nested `minItems` and `maxItems` are unsupported

- **GIVEN** `output_schema` contains either `minItems` or `maxItems` at any nested schema position
- **WHEN** `codex_cli()` is constructed
- **THEN** construction SHALL fail before agent execution
- **AND** the error SHALL identify every unsupported keyword and its JSON Pointer path.

#### Scenario: Multiple unsupported paths

- **GIVEN** the schema contains unsupported constraints at more than one nested path
- **WHEN** validation runs
- **THEN** the error SHALL report all discovered unsupported paths in deterministic order
- **SO THAT** callers can repair the schema in one iteration.

### Requirement: Positive bridge-representable schema

A schema that uses only constraints represented by the active Inspect `JSONSchema` model SHALL pass the representability gate.

#### Scenario: `type + enum` exact-value constraint

- **GIVEN** `output_schema` contains `{"type":"string","enum":["case-1"]}`
- **WHEN** `codex_cli()` is constructed
- **THEN** construction SHALL succeed
- **AND** the schema SHALL be staged without semantic rewriting
- **AND** the staged content SHALL retain both `type` and `enum`.

### Requirement: Validation is preservation, not schema rewriting

Inspect-SWE SHALL validate whether the caller's constraint semantics survive the bridge. It SHALL NOT synthesize semantically similar replacements for unsupported keywords.

#### Scenario: Unsupported `const`

- **GIVEN** the caller supplies `{"const":"case-1"}`
- **WHEN** validation runs
- **THEN** Inspect-SWE SHALL reject the schema
- **AND** SHALL NOT replace it with `enum`
- **AND** SHALL NOT add a `type`
- **AND** SHALL NOT otherwise weaken or reinterpret the contract.

### Requirement: Zero-model-call fail-closed behavior

Bridge-representability validation and JSON serialization validation SHALL complete synchronously during `codex_cli()` construction.

#### Scenario: Invalid schema is rejected at construction

- **GIVEN** an unsupported output schema
- **WHEN** the caller evaluates `codex_cli(output_schema=...)`
- **THEN** the call SHALL raise before returning an executable agent
- **AND** no model API request SHALL be possible from that failed construction.

### Requirement: Deterministic schema materialization

Equivalent validated schema objects SHALL produce stable serialized schema content.

#### Scenario: Equivalent schema is staged repeatedly

- **WHEN** the same validated schema object is used across repeated runs
- **THEN** serialization SHALL use deterministic key ordering and compact stable JSON encoding
- **SO THAT** callers can hash the staged contract for provenance.

### Requirement: Native Codex enforcement

Inspect-SWE SHALL use Codex CLI's native final-output schema mechanism rather than a substitute parser or repair layer.

- It SHALL NOT extract a JSON substring from unconstrained model output.
- It SHALL NOT strip markdown fences or leading/trailing prose.
- It SHALL NOT convert schema constraints into prompt prose.

### Requirement: Preserve Inspect bridge behavior

Final-output schema enforcement SHALL compose with `sandbox_agent_bridge()`.

Model routing, model-event attribution, tool bridging, retries, checkpoints, transcript behavior, and accounting SHALL remain available.

### Requirement: Explicit unsupported-mode behavior

When `output_schema` is supplied with Centaur mode, `codex_cli()` SHALL raise a clear construction-time error and SHALL NOT run as though the schema had been honored.

### Requirement: Serialization failure is construction-time

If the supplied schema cannot be deterministically serialized as JSON, `codex_cli()` SHALL raise an actionable construction-time error.

Codex SHALL NOT launch without the requested constraint.

### Requirement: Backward compatibility

The feature SHALL be opt-in. Existing callers that omit `output_schema` SHALL retain current behavior.

## Design

### Representability algorithm

Use the active Inspect response-schema model as the source of truth:

```python
from inspect_ai.util._json import JSONSchema
```

Walk only schema-valued positions that the bridge itself models:

- `items`
- `additionalProperties`
- values under `properties`
- entries under `anyOf`

Do not recurse into arbitrary client values held by `default`, `enum`, or `examples`, because objects there are data rather than nested schemas.

At each schema object:

1. compare keyword names against `JSONSchema.model_fields`;
2. exclude the bridge's known non-constraining annotations;
3. record every remaining unsupported keyword by RFC 6901 JSON Pointer;
4. recurse through modeled nested schema positions;
5. raise once with the complete deterministically sorted path set.

This mirrors the semantic boundary already present in Inspect AI `0.3.268` without changing Inspect AI production behavior.

### Construction-time preparation

Validate and serialize once in the outer `codex_cli()` constructor:

```python
serialized_output_schema = _prepare_output_schema(output_schema)
```

`_prepare_output_schema()` SHALL:

- return `None` when no schema is requested;
- detect unsupported constraint keywords;
- reject them with paths;
- deterministically `json.dumps(..., sort_keys=True, separators=(",", ":"))`;
- convert JSON serialization failures into actionable configuration errors.

The async execution closure then only stages the already-validated serialized bytes. It does not reinterpret the schema.

### Sandbox staging

After `CODEX_HOME` exists, write the pre-serialized schema to a stable sandbox-local file such as:

```text
<CODEX_HOME>/final-output.schema.json
```

Then append:

```text
--output-schema <sandbox-schema-path>
```

to headless `codex exec`.

### Why validation belongs in Inspect-SWE

A caller using `codex_cli(output_schema=...)` is asking Inspect-SWE to honor that schema through its bridge. If the bridge will weaken it, accepting the argument would create false provenance: the caller would record a schema that was never actually enforced.

Failing at construction makes the unsupported boundary explicit and costs zero model calls.

### Why rewriting does not belong in Inspect-SWE

Rewriting `const` to `enum`, removing cardinality constraints, expanding references, or otherwise finding a bridge-compatible equivalent changes the caller's schema representation and can alter semantics.

That policy belongs to the caller that owns the contract. Inspect-SWE should only determine whether it can preserve what it was given.

## Tests

### Focused unit tests

1. `codex_cli(output_schema=None)` preserves no-schema behavior.
2. `type + enum` passes construction.
3. nested `const` fails at construction and reports its JSON Pointer.
4. nested `minItems` fails at construction and reports its JSON Pointer.
5. nested `maxItems` fails at construction and reports its JSON Pointer.
6. multiple unsupported constraints are reported together in deterministic order.
7. unsupported constraints fail before any sandbox/bridge/model interaction.
8. non-serializable values fail at construction.
9. Centaur + `output_schema` fails at construction.
10. deterministic materialization preserves the validated schema exactly.
11. headless command construction includes `--output-schema` and the sandbox path.
12. omission of `output_schema` emits no output-schema flag.
13. existing Codex CLI tests remain green.

### Positive regression fixture

At minimum, exercise:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "case_id": {
      "type": "string",
      "enum": ["case-1"]
    }
  },
  "required": ["case_id"]
}
```

### Negative regression fixture

At minimum, exercise nested paths equivalent to the live failure:

```json
{
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
                "const": "case-1"
              }
            }
          }
        ]
      }
    }
  }
}
```

Expected rejected paths:

```text
/properties/records/minItems
/properties/records/maxItems
/properties/records/items/anyOf/0/properties/case_id/const
```

No model call is permitted.

## Inspect AI verification

Do not broaden Inspect AI as part of this PR.

For pinned Inspect AI `0.3.268`:

- `client_json_schema()` already identifies unmodelled keywords and warns that they are dropped;
- `JSONSchema` models `type`, `format`, `description`, `default`, `enum`, `items`, `properties`, `additionalProperties`, `anyOf`, `required`, `pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, and `examples`;
- `const`, `minItems`, and `maxItems` are not modeled in that runtime.

If Inspect AI later gains a public schema-representability helper, Inspect-SWE MAY switch to that API in a separate narrow cleanup. This PR should not require an Inspect AI production API change.

## Downstream Agent-Workflow adaptation

The `routing-semantic-v2` benchmark SHALL supply only the bridge-representable generation-time subset.

Specifically:

- replace `{"const": case_id}` with `{"type":"string","enum":[case_id]}`;
- remove generation-time `minItems` / `maxItems` from `records`;
- remove generation-time `minItems` / `maxItems` from `decisive_case_evidence`;
- retain exact case-set cardinality in deterministic post-generation validation;
- retain 1–3 evidence-item cardinality in deterministic post-generation validation;
- retain strict whole-completion JSON parsing and all existing seam/label/justification checks.

This is a caller-owned schema adaptation, not an Inspect-SWE rewrite.

## Downstream compatibility-patch rollover

The private qualification host may already have capability v1 patched into the installed Inspect-SWE 0.2.71 source.

Capability v2 SHALL NOT patch over those already-mutated bytes. Before installing the v2 compatibility layer, restore the exact pristine Inspect-SWE 0.2.71 wheel bytes, for example:

```bash
python -m pip install --force-reinstall --no-deps inspect-swe==0.2.71
```

Then apply capability v2 and freeze a new runtime lock.

The v2 patch detects the legacy v1 marker and fails with this remediation rather than silently stacking two source mutations.

## Qualification gate

The upstream/local change is not sufficient evidence by itself.

Before opening the upstream PR:

1. install the fail-closed local implementation;
2. freeze a new runtime identity if the local compatibility capability changes;
3. rerun the complete `routing-semantic-v2` IA-1 through IA-11 qualification;
4. preserve any newly surfaced integration failure as evidence;
5. do not authorize real A/B/C until qualification genuinely passes.

The failed `const`/`minItems`/`maxItems` qualification attempt remains preserved as a historical integration checkpoint.
