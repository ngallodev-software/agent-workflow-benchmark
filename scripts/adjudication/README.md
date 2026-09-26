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
- `p0b-run-c.sh` — run and validate C only when the persisted dispute view contains cases.
- `p0b-prepare-resolutions.sh` — identify genuine three-way A/B/C conflicts and create private resolution/review artifacts.
- `p0b-freeze.sh` — prepare/check three-way resolutions when needed, then freeze the oracle.
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

For the current `deepseek-flash` cohort, the explicit recovery command is:

~~~bash
FORCE_REQUALIFY=1 MODEL_ID=deepseek-flash \
  bash scripts/adjudication/p0a-qualify.sh
~~~

Do **not** delete `runtime-lock.json` for this recovery. The runtime lock freezes Inspect AI, Inspect SWE, the resolved Codex CLI version, and Docker identity; P0A records the adjudicator model separately.

After recovery, verify the replacement before P0B:

~~~bash
bash scripts/adjudication/verify-qualification.sh
~~~

The verifier must report `qualified: true`, IA-1 through IA-8 as `pass`, and:

~~~text
IA-2 model: openai-api/codex-lb/deepseek-flash
~~~

## Path discovery and portability

The workflow scripts do not contain machine-specific installation roots.

Path resolution works as follows:

- `BENCH_REPO` is derived from the physical location of `scripts/adjudication/env.sh`.
- `AW` uses an explicit environment override first, then an installed `agent-workflow` found on `PATH`, then the conventional sibling checkout `agent-workflow/.venv/bin/agent-workflow` only as a fallback.
- `PYTHON` uses an explicit override first, then the Python executable beside the resolved `AW`, then `python3` on `PATH`.
- `COMP_REPO` uses an explicit override first and otherwise auto-detects a sibling `agent-workflow-comparative-eval` checkout.
- `PRIVATE_ROOT` defaults under `$XDG_DATA_HOME`, or `$HOME/.local/share` when XDG data storage is not configured.
- Study file paths are derived from those roots.

A non-sibling installation is supported explicitly:

~~~bash
export COMP_REPO=/path/to/agent-workflow-comparative-eval
export AW=/path/to/venv/bin/agent-workflow
# PYTHON normally resolves beside AW; override it only when necessary.

bash /path/to/agent-workflow-benchmark/scripts/adjudication/verify-qualification.sh
~~~

The scripts can be launched from any current working directory because they locate their own benchmark checkout from the script path.

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

## Script execution and C detection

All `.sh` files in this directory are committed with executable mode. A normal
Git clone/pull should therefore allow either form:

~~~bash
./scripts/adjudication/p0b-run-c.sh
bash scripts/adjudication/p0b-run-c.sh
~~~

The scripts also invoke one another through `bash`, so the second form remains
usable on filesystems or archive transfers that do not preserve Unix execute
bits.

After `p0b-compute-disputes.sh`, C is required whenever the generated dispute
view contains one or more entries in its `cases` array. The `requires_c`
value printed by the dispute-export command is a command result; it is not a
field in the persisted dispute-view JSON. The staged scripts therefore inspect
the persisted `cases` array directly.

## Three-way conflicts after C

If A, B, and C all choose different labels for the same decision seam, there is
no two-of-three majority. The oracle contract requires a recorded adjudication
resolution rather than silently choosing one model's answer.

Prepare the review artifacts with:

~~~bash
bash scripts/adjudication/p0b-prepare-resolutions.sh
~~~

This writes private artifacts under `$ORACLE_RUN`:

~~~text
resolutions.json
resolution-review.json
~~~

`resolution-review.json` contains each genuine three-way conflict, including
the source task, decision-seam contract, allowed labels, and the A/B/C votes.

`resolutions.json` is the schema-valid artifact consumed by oracle freeze. Each
generated record starts as:

~~~json
{
  "case_id": "...",
  "decision_id": "...",
  "status": "unresolved",
  "rationale": "TODO: record the adjudication rationale for this three-way conflict.",
  "participants": []
}
~~~

After human review, either:

- change `status` to `resolved`, add the chosen valid `label`, replace the
  TODO with the adjudication rationale, and record participants; or
- intentionally leave `status: unresolved`, replace the TODO with the reason
  the oracle conflict remains unresolved, and record participants.

By default `p0b-freeze.sh` refuses to freeze while TODO text remains and also
refuses explicit unresolved conflicts. To intentionally preserve unresolved
oracle conflicts, set:

~~~bash
ALLOW_UNRESOLVED_RESOLUTIONS=1 bash scripts/adjudication/p0b-freeze.sh
~~~

Do not use that override merely to bypass adjudication.

## Output safety

The scripts refuse to overwrite an existing non-empty `ORACLE_RUN`. To repeat P0B, choose a new private output root, for example:

~~~bash
ORACLE_RUN="$PRIVATE_ROOT/oracle-run-02" bash scripts/adjudication/p0b-run-ab.sh
~~~

Private qualification and oracle evidence must not be committed to the repository.
