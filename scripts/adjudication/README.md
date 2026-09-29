# Inspect oracle adjudication scripts

These scripts preserve the historical `routing-semantic-v1` P0A/P0B oracle procedure and provide the separately versioned `routing-semantic-v2` full qualification entrypoint.

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
- `p0b-render-resolution-review.sh` — render the private machine review JSON as a human-readable Markdown worksheet with the verbatim case prompt, explicit oracle question, rubric, metadata, and A/B/C votes.
- `p0b-freeze.sh` — prepare/check three-way resolutions when needed, then freeze the oracle.
- `p0b-validate-oracle.sh` — validate the final oracle against the frozen corpus.
- `run-all.sh` — end-to-end driver. It creates P0A when missing, retries an incomplete/invalid P0A after archiving it, and verifies/preserves an existing passing qualification.
- `v2-qualify.sh` — freeze/reuse the routing-semantic-v2 runtime lock and run the complete frozen-protocol IA-1 through IA-11 qualification without starting the real 120-case cohort.

## routing-semantic-v2 full qualification

The successful development preflight is the gate that permits freezing the real-v2
study/dataset/protocol/module identities. It is not reused as the final qualification
evidence because it predates those frozen identities.

After the v2 identities and module pair are frozen, run:

~~~bash
bash scripts/adjudication/v2-qualify.sh
~~~

The runner:

1. requires benchmark `0.6.0` and comparative-eval `0.3.1`;
2. uses `routing-semantic-v2.inspect.module.json`, whose authoring-view, protocol,
   and corpus inputs are hash-pinned;
3. creates the v2 runtime lock once and reuses it on qualification retries;
4. runs IA-1 through IA-8 under that locked runtime;
5. reruns the IA-9/10/11 evidence preflight under the same locked Codex version,
   frozen `routing-semantic-oracle-v2.0.0` protocol, and DeepSeek model identity;
6. emits one `inspect-adjudication-qualification/v2` artifact that can report
   `qualified=true` only when all eleven gates pass.

The expected terminal boundary is:

~~~text
routing-semantic-v2 full qualification: PASS
IA-1 pass
...
IA-11 pass
qualified: True
~~~

This still does **not** start real A/B/C adjudication. Inspect the generated runtime
lock and qualification artifact before authorizing the 120-case cohort.

A failed attempt is preserved. To archive its generated qualification evidence and
retry against the same runtime lock:

~~~bash
FORCE_V2_QUALIFICATION=1 bash scripts/adjudication/v2-qualify.sh
~~~

The v2 qualifier keeps the terminal intentionally compact. Inspect/model-API output
is written to the private qualification root as `qualification-run.log` rather
than streamed to stdout. On a forced retry that log is archived beside the
corresponding `inspect-qualification` directory and any qualification manifest.

For structured-output transport diagnosis, prefer the sanitized Codex-LB ingress
capture. It forwards each request body byte-for-byte to the already-running local
Codex-LB but records only method/path/model plus the structured-output format
controls and a canonical schema SHA-256. It never records prompts, input/messages,
tool arguments, header values, model responses, or full schemas:

~~~bash
V2_CAPTURE_CODEX_LB_INGRESS=1 FORCE_V2_QUALIFICATION=1 \
  bash scripts/adjudication/v2-qualify.sh
~~~

The private capture is `codex-lb-ingress.jsonl`; the diagnostic compares its
schema hashes against the persisted primary and C `codex-output-schema.json`
artifacts and labels matching requests as `primary` or `C`.

Raw Inspect model-API logging remains available when specifically needed and is
still captured only in the private run log:

~~~bash
V2_LOG_MODEL_API=1 FORCE_V2_QUALIFICATION=1 \
  bash scripts/adjudication/v2-qualify.sh
~~~

Use the repository-owned non-leaking diagnostic instead of ad-hoc `rglob`
snippets:

~~~bash
python scripts/adjudication/v2-diagnose.py --attempt current
python scripts/adjudication/v2-diagnose.py --list-attempts
python scripts/adjudication/v2-diagnose.py --attempt retry:<UTC-stamp>
~~~

The diagnostic never falls back from `current` to an archived retry. New runs
also write a private `attempt.json` containing the explicit UTC attempt id,
model, model-API logging mode, and terminal status; forced retries archive that
identity beside the matching evidence.

The diagnostic reports only qualification state, sample status, completion
classification, persisted structured-output schema hashes/content constraints,
and structured-output request metadata when Inspect exposes it. It does not
print prompts, full model answers, response bodies, tool arguments, or secrets.

The earlier standalone `routing-semantic-v2-preflight/preflight.json` remains
historical development evidence; the full qualifier deliberately produces fresh
IA-9/10/11 evidence under the final frozen identities.

## routing-semantic-v2 real oracle cohort

After `v2-qualify.sh` produces a passing
`inspect-adjudication-qualification/v2` manifest, use the dedicated v2 driver.
Do not reuse the historical `p0b-*` entrypoints for v2: those remain the
versioned v1 workflow and their defaults intentionally target
`routing-semantic-v1`.

First verify the private qualification and exact frozen inputs without making a
model call:

~~~bash
bash scripts/adjudication/v2-oracle.sh verify
~~~

The verifier requires:

- Agent-Workflow `0.11.12`, benchmark `0.6.3`, and comparative-eval `0.3.1`;
- no tracked or staged changes in the benchmark or comparative-eval checkouts;
- installed benchmark adjudication/compat source files to byte-match the benchmark checkout;
- installed v2 comparative study/corpus resources to byte-match the comparative-eval checkout;
- `qualified=true`;
- IA-1 through IA-11 all `pass`;
- the qualification module/runtime-lock hashes to match the supplied files;
- model `openai-api/codex-lb/deepseek-flash`;
- the real v2 authoring view, oracle protocol, and corpus SHA-256 values to
  match the frozen module.

The default private real-cohort root is:

~~~text
~/.local/share/agent-workflow/routing-semantic-v2-oracle/run-01
~~~

Run the real independent A/B cohort:

~~~bash
bash scripts/adjudication/v2-oracle.sh run-ab
~~~

Before the first provider call the driver writes immutable private
`run-identity.json` evidence binding the cohort to the benchmark/comparative
Git heads, package versions, runtime-lock bytes, qualification bytes and
qualification attempt id, module bytes, and frozen view/protocol/corpus hashes.

The model-stage console stays compact. Full Inspect/Codex output is retained
under the private v2 oracle log root. By default the driver also places the
sanitized loopback Codex-LB ingress observer in the same path qualified by the
successful v2 retry. For each real model stage it requires every observed
DeepSeek `POST /v1/responses` request to carry:

- `text.format.type=json_schema`;
- `strict=true`;
- the exact SHA-256 of the persisted stage `codex-output-schema.json`.

The sanitized observer retains no prompts, input/messages, tool arguments,
header values, model responses, or full schemas. Set
`V2_CAPTURE_CODEX_LB_INGRESS=0` only for an explicitly documented reason;
the driver requires a non-empty `V2_CAPTURE_OVERRIDE_REASON` when capture is
disabled. The default keeps the diagnostic evidence needed if the intermittent
v20 structured-output failure recurs.

Continue only after A/B pass validation:

~~~bash
bash scripts/adjudication/v2-oracle.sh compute-disputes
bash scripts/adjudication/v2-oracle.sh run-c
~~~

If a later code fix affects only deterministic validation, revalidate already
preserved model outputs without another provider call:

~~~bash
bash scripts/adjudication/v2-oracle.sh validate-ab
bash scripts/adjudication/v2-oracle.sh validate-c
~~~

`run-c` exits cleanly without a model call when the blinded dispute view
contains no cases. When C is required, the same strict ingress and whole-output
boundaries apply.

For a staged end-to-end run:

~~~bash
bash scripts/adjudication/v2-oracle.sh run-all
~~~

`run-all` deliberately stops if any three-way conflict requires human
resolution. It writes the private review worksheet and machine resolution
artifact; after review, continue with:

~~~bash
bash scripts/adjudication/v2-oracle.sh freeze
bash scripts/adjudication/v2-oracle.sh validate-oracle
~~~

At every stage, inspect compact state with:

~~~bash
bash scripts/adjudication/v2-oracle.sh status
~~~

The real model stages are never retried in place. If A/B or C fails after a
provider call, preserve that run and choose a new explicit `V2_ORACLE_RUN`
only as part of a documented methodological decision. Deterministic validation
stage logs may be rerun; previous logs are archived rather than overwritten.

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

`resolution-review.json` contains the machine-readable review evidence. The preparation step also writes `resolution-review.md`, which is the preferred human review surface. It contains the verbatim case prompt, the explicit question being decided, supplied metadata, the frozen rubric, and the A/B/C votes.

If the JSON already exists from an earlier run, render the Markdown without regenerating any adjudication artifacts:

~~~bash
bash scripts/adjudication/p0b-render-resolution-review.sh
~~~

The field meanings and review rules are documented in the comparative-eval library at:

`docs/studies/routing-semantic-v1-oracle-review-guide.md`

That guide is non-normative; the frozen oracle protocol remains authoritative.

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

### Reading the authoring-view fields

The human reviewer should not have to infer meaning from raw JSON:

- `task` is the verbatim request being labeled.
- `metadata` is supplied evidence and may be stale or misleading; it is not an answer key.
- `oracle_eligible` says which oracle questions require labels. A value of `true` means "label this seam", not "the label is true".
- `decision_seams` defines the allowed answer space and rubric.
- A/B/C votes explain why human adjudication is required; they are not themselves evidence about the live system.

For semantic risk, judge the consequence of acting on a materially wrong interpretation of the **frozen case**. Do not import knowledge of local credentials, real deployment automation, private repository contents, or portfolio infrastructure unless the case itself contains that information.

## Output safety

The scripts refuse to overwrite an existing non-empty `ORACLE_RUN`. To repeat P0B, choose a new private output root, for example:

~~~bash
ORACLE_RUN="$PRIVATE_ROOT/oracle-run-02" bash scripts/adjudication/p0b-run-ab.sh
~~~

Private qualification and oracle evidence must not be committed to the repository.
