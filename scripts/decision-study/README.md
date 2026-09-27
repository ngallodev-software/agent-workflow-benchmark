# Routing Semantic decision-study phase scripts

These scripts continue `routing-semantic-v1` after the independent oracle has
been frozen and validated.

## Phase map

~~~text
P0A  authenticated adjudicator qualification      complete before this lane
P0B  independent frozen oracle                    complete before this lane
P1   bounded live instrumentation smoke           scripts here
P2   full 120-case preregistered inference/report scripts here
P3   sanitized publication preparation            scripts here
~~~

## Environment and portability

`env.sh` derives the benchmark checkout from its own location. It prefers an
explicit `AW`, then `agent-workflow` on `PATH`, then the conventional sibling
shared virtual environment. The comparative-eval checkout is similarly
overridable with `COMP_REPO`.

Private outputs default under:

~~~text
$XDG_DATA_HOME/agent-workflow/routing-semantic-v1-decision-study
~~~

or `$HOME/.local/share/...` when XDG data storage is not configured.

No script depends on a machine-specific installation root.

## P1 — instrumentation smoke

Preferred entry point:

~~~bash
bash scripts/decision-study/p1-all.sh
~~~

It executes:

~~~text
p1-prepare-smoke.sh
        |
        v
p1-run-smoke.sh
        |
        v
p1-verify-smoke.sh
~~~

The default sample size is 8 cases. Override it only for development purposes:

~~~bash
P1_SAMPLE_SIZE=12 bash scripts/decision-study/p1-all.sh
~~~

The P1 corpus is a private derived subset of the frozen 120-case corpus. The
canonical corpus is never modified. Selection is deterministic:

~~~text
ascending sha256(source_corpus_sha256 + ":" + case_id)
~~~

`selection.json` records the exact frozen source-corpus SHA-256, selection
algorithm, sample size, and selected case IDs.

P1 remains deliberately below the frozen minimum `n=100` threshold and is
development evidence only. It must not be presented as comparative effectiveness
evidence.

The verifier checks:

- one provider request per observed case;
- three routing observations per observed case;
- request IDs are unique;
- Choice/Noul/Score probability evidence survives persistence;
- failures/exclusions remain explicit;
- the oracle is absent during inference;
- neutral evidence privacy flags prohibit raw/secret persistence;
- the live `TYPESAFE_API_KEY` value does not appear in the run tree;
- token/usage evidence is request-level rather than copied into observations;
- question set is `routing/v2`;
- projector is `routing-state/v2`.

A successful verifier writes `verification.json` with `status: "pass"`.

To repeat P1 while preserving prior evidence, choose a new root:

~~~bash
P1_ROOT="$DECISION_STUDY_ROOT/p1-smoke-02" \
  bash scripts/decision-study/p1-all.sh
~~~

## P2 — full preregistered run

P2 refuses to start unless the selected P1 verification artifact reports
`status: "pass"`.

Preferred entry point:

~~~bash
bash scripts/decision-study/p2-all.sh
~~~

This first executes all 120 frozen cases **without an oracle argument**. Only
after inference completes does `p2-report.sh` validate and join the separately
frozen oracle.

Individual steps:

~~~bash
bash scripts/decision-study/p2-run-full.sh
bash scripts/decision-study/p2-report.sh
~~~

P2 results must be inspected for exclusions, denominators, eligibility,
calibration, uncertainty, and limitations regardless of outcome direction.

## P3 — sanitized publication preparation and verification

Preferred entry point after P2 review:

~~~bash
bash scripts/decision-study/p3-all.sh
~~~

It executes:

~~~text
p3-publish-prepare.sh
        |
        v
p3-verify-public.sh
~~~

The publication pipeline now uses a public oracle projection rather than copying
the private frozen oracle verbatim. It retains final frozen labels and per-seam
resolution status/method while removing:

- adjudicator identities;
- individual A/B/C votes;
- adjudication-pass hashes/timestamps;
- recorded-discussion rationale;
- participant identities;
- private reasoning-summary artifacts.

The prepare step also fails closed on unexpected files, symlinks, host-local
path markers, private adjudication keys, privacy-flag violations, and the live
`TYPESAFE_API_KEY` value when present.

The verification step independently requires:

- the exact publication file allowlist;
- valid `MANIFEST.sha256`;
- a study-eligible 120-case cohort;
- 120 public oracle records;
- 120 provider requests;
- 360 observations;
- 360 oracle outcomes;
- 0 exclusions;
- 120 oracle-eligible observations per seam;
- the public oracle projection contract;
- no reasoning-summary/private human-adjudication fields.

A successful verification writes, outside the public tree:

~~~text
$P3_ROOT/verification.json
~~~

with `status: "pass"`.

P3 does not automatically push or copy the result to `benchmark-results` or a
portfolio site. Publication remains a separate reviewed action.

## Frozen identities

The scripts enforce the frozen corpus SHA-256:

~~~text
e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280
~~~

and retain these study identities:

~~~text
study              routing-semantic-v1
dataset            routing-semantic-corpus-v1.0.0
question set       routing/v2
projector          routing-state/v2
~~~

The frozen oracle is never passed to either P1 or P2 inference.
