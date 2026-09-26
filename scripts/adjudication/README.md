# Inspect oracle adjudication scripts

These scripts make the `routing-semantic-v1` P0A/P0B oracle procedure reproducible without copying command blocks from the operator guide.

## Layout

- `env.sh` — sourceable path/provider environment for the study.
- `lib.sh` — shared verification and cohort-model helpers.
- `p0a-qualify.sh` — create or deliberately replace P0A qualification.
- `verify-qualification.sh` — verify `qualified=true`, IA-1 through IA-8, module/runtime-lock hashes, and the IA-2 model.
- `verify-frozen-inputs.sh` — verify the frozen authoring-view and corpus SHA-256 values.
- `p0b-run-ab.sh` — verify P0A, set up paths/model, verify frozen inputs, then start real A/B.
- `p0b-validate-ab.sh` — validate both authoritative A/B passes.
- `p0b-compute-disputes.sh` — produce the blinded dispute view for C.
- `p0b-run-c.sh` — run and validate C only when `requires_c=true`.
- `p0b-freeze.sh` — freeze the oracle, optionally using `RESOLUTIONS=/path/to/file.json`.
- `p0b-validate-oracle.sh` — validate the final oracle against the frozen corpus.
- `run-all.sh` — end-to-end driver. It creates P0A when missing, retries an incomplete/invalid P0A after archiving it, and verifies/preserves an existing passing qualification.

## Model selection

P0A is the point where an adjudicator model is selected.

~~~bash
bash scripts/adjudication/p0a-qualify.sh
~~~

The default is:

~~~text
deepseek-flash
~~~

To deliberately start a different P0A cohort:

~~~bash
MODEL_ID=<codex-lb-model-id> bash scripts/adjudication/p0a-qualify.sh
~~~

P0B does **not** independently choose a default model. It reads the exact fully-qualified model from the passing P0A `IA-2.evidence.model`. If `MODEL_ID` or `ADJUDICATION_MODEL` is supplied during P0B, it is treated as an assertion and must match the qualified model exactly.

This prevents a run from qualifying one adjudicator and silently producing real oracle labels with another.

## Runtime lock versus model

`runtime-lock.json` freezes the runtime cohort: Inspect AI, Inspect SWE, the resolved Codex CLI version, and Docker identity. It is intentionally reused when P0A is rerun with a different adjudicator model.

The selected adjudicator model is recorded separately in the P0A qualification manifest. Therefore changing from a previously qualified model to another model requires replacing/re-running P0A qualification, but does **not** require deleting the runtime lock.

Use `FORCE_REQUALIFY=1` to deliberately replace an already-passing qualification. The old qualification/evidence is archived under `$PRIVATE_ROOT/retries/`.

## Typical manual workflow

Set up variables in the current shell when desired:

~~~bash
source scripts/adjudication/env.sh
~~~

Verify a passing P0A:

~~~bash
bash scripts/adjudication/verify-qualification.sh
~~~

Start real A/B:

~~~bash
bash scripts/adjudication/p0b-run-ab.sh
~~~

Then continue:

~~~bash
bash scripts/adjudication/p0b-validate-ab.sh
bash scripts/adjudication/p0b-compute-disputes.sh
bash scripts/adjudication/p0b-run-c.sh
bash scripts/adjudication/p0b-freeze.sh
bash scripts/adjudication/p0b-validate-oracle.sh
~~~

Or run the full procedure from the current qualification state:

~~~bash
bash scripts/adjudication/run-all.sh
~~~

## Output safety

The scripts refuse to overwrite an existing non-empty `ORACLE_RUN`. To repeat P0B, choose a new private output root, for example:

~~~bash
ORACLE_RUN="$PRIVATE_ROOT/oracle-run-02" bash scripts/adjudication/p0b-run-ab.sh
~~~

Private qualification and oracle evidence must not be committed to the repository.
