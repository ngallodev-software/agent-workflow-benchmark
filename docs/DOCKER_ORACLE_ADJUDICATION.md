# Docker Oracle Adjudication Harness

This harness runs the frozen `routing-semantic-v1` independent oracle adjudication on a Debian Docker host without exposing Agent-Workflow treatment outputs to the adjudicators.

It is intentionally split into two trust domains:

- **Host coordinator:** the existing shared Agent-Workflow virtualenv. It verifies hashes, validates completed adjudication passes, computes A/B disagreements, prepares the C-only dispute view, and freezes the final oracle.
- **Adjudicator containers:** clean Codex CLI containers. They receive only their own blinded input mount, a minimal Codex provider configuration, and their own output mount.

Agent-Workflow, the benchmark plugin, comparative decision outputs, and TypeSafe/Jev credentials are **not installed or mounted inside A/B/C adjudicator containers**.

## Why containers instead of Git worktrees?

The study requires informational independence, not separate physical machines. Two containers on the same Debian host are sufficient when their visible files are separated.

A normal Git worktree is a weaker boundary because an agent with shell access can inspect repository refs, history, sibling worktrees, or other local paths. The Docker harness instead gives each adjudicator:

- a read-only container root filesystem;
- a private read-only input bind mount;
- a private read/write output bind mount;
- no repository checkout;
- no Docker socket;
- no sibling adjudicator mount;
- no treatment output;
- no TypeSafe credential;
- an ephemeral Codex home under container `/tmp`;
- a read-only Codex execution sandbox;
- web search disabled;
- shell-network access disabled by Codex policy.

Docker networking remains enabled only because the Codex CLI must reach the configured model provider/load balancer. Set `ADJUDICATION_DOCKER_NETWORK` to a host network with stricter egress policy if one is available.

## Frozen inputs

A/B are prepared from the exact committed comparative-eval artifact:

`docs/studies/artifacts/routing-semantic-v1/oracle-authoring-view.json`

Expected SHA-256:

`a5a40224793a50d9371e9ae437e144b15812829ba1cd56a5564dc6ba28846a0a`

Frozen corpus SHA-256:

`e4b33df3b3752b32cdb362833765cc8f0c9cc024473071209563d73284011280`

The preparation script refuses to continue if either identity changes.

## Declarative module identity

The Docker runner is the frozen reference executor for this study. Its configuration is also captured as a versioned module instance:

`modules/abc-adjudication/routing-semantic-v1.module.json`

Validate it with:

~~~bash
agent-workflow benchmark adjudication-module-validate \
  modules/abc-adjudication/routing-semantic-v1.module.json
~~~

The module declares the prompt, required files and hashes, A/B/C identities, runtime image/agent version, credential policy, guardrails, output contract, delayed-reveal policy, C-dispute routing, and final result locations.

This module is intentionally separate from the historical runner. Future generic execution can consume the same contract after parity testing without changing the frozen routing-semantic-v1 study implementation.

See:

- [A/B/C Adjudication Module](../modules/abc-adjudication/README.md)
- [Isolated Agent Execution Architecture](architecture/ISOLATED_AGENT_EXECUTION.md)
- [Prior Art and Standards](PRIOR_ART_AGENT_SANDBOXING.md)
- [ADR-0001](decisions/ADR-0001-isolated-agent-sandboxing.md)
- [Historical Record](history/2026-09-25-routing-semantic-oracle-containerization.md)

## Prerequisites on the Debian host

1. Docker Engine is installed and the current user can run `docker`.
2. `agent-workflow-benchmark` and `agent-workflow-comparative-eval` are checked out as sibling repositories, or `COMPARATIVE_EVAL_REPO` points at the comparative-eval checkout.
3. The current Agent-Workflow + benchmark plugin are installed in the shared virtualenv.
4. You provide a **minimal adjudicator-specific Codex `config.toml`** that contains only model/provider/auth configuration needed to reach your load balancer.
5. You provide a separate environment file containing only environment variables required by that Codex provider configuration.

Do not reuse a full interactive Codex config containing MCP servers, plugins, browser configuration, notification hooks, or instruction-file overrides. The harness checks and rejects those top-level configuration keys.

The Codex config can use normal user-level model-provider settings such as `model_provider`, `model_providers`, or `openai_base_url`. The file is copied into an ephemeral `CODEX_HOME` inside each container and is never committed.

### Credential separation

**Do not put `TYPESAFE_API_KEY` in the adjudicator environment file.**

Oracle adjudication happens before live TypeSafe/Jev inference and must remain blind to treatment behavior. The launcher rejects any `TYPESAFE_*` entry in the file passed to the containers.

If your Codex load-balancer configuration uses an environment-backed provider token, create a file outside the repository such as:

~~~dotenv
CODEX_PROXY_TOKEN=replace-me
~~~

The checked-in `docker/adjudication/codex-adjudicator.env.example` is only a template.

## One-command A/B startup

From the benchmark repository:

~~~bash
export AGENT_WORKFLOW_VENV=/path/to/shared-agent-workflow-venv
export CODEX_CONFIG=/secure/path/adjudicator-config.toml
export CODEX_ENV_FILE=/secure/path/codex-adjudicator.env

bash scripts/run-docker-oracle-adjudication.sh start-ab
~~~

`start-ab` performs, in order:

1. verifies the frozen corpus and authoring-view SHA-256 identities;
2. copies the same blinded view and protocol into two separate runtime directories;
3. generates an output schema bound to all expected cases/seams;
4. generates a starting prompt for `codex-a` and `codex-b`;
5. builds one adjudicator image using the pinned current Codex CLI release (`@openai/codex@0.156.1`);
6. records the exact installed `codex --version` and Docker image ID;
7. starts A and B concurrently as separate containers;
8. waits for both to finish before exposing either result to the coordinator;
9. wraps the model-only label output in the benchmark adjudication-pass contract;
10. validates both completed passes against the exact frozen A/B view.

The default private runtime directory is:

`.adjudication/routing-semantic-v1/`

It is ignored by Git.

## Runtime layout

~~~text
.adjudication/routing-semantic-v1/
├── run-manifest.json
├── coordinator/
│   ├── oracle-authoring-view.json
│   ├── oracle-authoring-view.manifest.json
│   ├── oracle-protocol.md
│   ├── routing-corpus.json
│   ├── docker-image-id.txt
│   ├── codex-version.txt
│   ├── validation-a.json
│   └── validation-b.json
├── a/
│   ├── input/
│   │   ├── oracle-view.json
│   │   ├── oracle-protocol.md
│   │   ├── START_PROMPT.md
│   │   ├── pass-metadata.json
│   │   └── model-output.schema.json
│   └── output/
│       ├── adjudication.json
│       ├── adjudication.json.sha256
│       ├── model-output.json
│       ├── codex-version.txt
│       ├── codex.stdout.log
│       └── codex.stderr.log
└── b/
    └── ...
~~~

The coordinator corpus contains construction strata and therefore is never mounted into an adjudicator container.

## Inspect A/B status

~~~bash
bash scripts/run-docker-oracle-adjudication.sh status
~~~

Do not manually compare or show the A/B output files to either adjudicator.

## Compare A and B after both finish

~~~bash
bash scripts/run-docker-oracle-adjudication.sh compare
~~~

This invokes the merged benchmark command:

~~~text
decision-study-oracle-disputes
~~~

and writes:

`coordinator/oracle-disputes-for-c.json`

Only after both independent A/B passes exist.

If A and B agree everywhere, the command reports that C is unnecessary.

If they disagree, the helper prepares a third private directory:

~~~text
c/
├── input/
│   ├── oracle-view.json
│   ├── oracle-protocol.md
│   ├── START_PROMPT.md
│   ├── pass-metadata.json
│   └── model-output.schema.json
└── output/
~~~

C receives only disputed cases/seams and never receives A/B label values.

## Run C when required

Use the same Codex provider config/environment:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh run-c
~~~

C runs in a third fresh container with adjudicator ID `codex-c`.

The completed pass is validated against the exact C dispute-view SHA-256.

## True three-way conflicts

If A, B, and C produce three distinct categorical labels, or risk labels `0/1/2`, the frozen protocol requires a recorded resolution artifact.

Create a file satisfying:

`agent-workflow-benchmark/decision-study-adjudication-resolutions/v1`

and the checked-in schema:

`src/agent_workflow_benchmark/schemas/decision-study-adjudication-resolutions.schema.json`

A resolution can either:

- record a valid resolved label and rationale; or
- remain explicitly `unresolved`, producing `oracle_conflict_unresolved`.

Then set:

~~~bash
export RESOLUTIONS_FILE=/secure/path/resolutions.json
~~~

Do not expose deterministic-control or TypeSafe/Jev outputs during that discussion.

## Freeze the oracle

After A/B and any required C/resolution work:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh freeze
~~~

The coordinator writes:

~~~text
coordinator/oracle.json
coordinator/oracle.json.manifest.json
coordinator/freeze-result.json
coordinator/final-validation.json
~~~

The sidecar manifest persists the final oracle SHA-256 and exact adjudication provenance.

**Do not run live TypeSafe/Jev comparative inference until these freeze artifacts exist and final validation succeeds.**

## Later inference

The Docker adjudication harness deliberately stops at the oracle-freeze boundary. Live comparative inference is still run separately:

~~~bash
agent-workflow benchmark decision-study-run \
  .adjudication/routing-semantic-v1/coordinator/routing-corpus.json \
  /path/to/run

agent-workflow benchmark decision-study-report \
  /path/to/run \
  .adjudication/routing-semantic-v1/coordinator/oracle.json
~~~

The inference command receives no oracle path.

## Individual commands

Prepare A/B without running them:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh prepare-ab
~~~

Build/rebuild the image:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh build
~~~

Run already-prepared A/B:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh run-ab
~~~

Compare completed A/B passes and prepare C if needed:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh compare
~~~

Run C:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh run-c
~~~

Freeze:

~~~bash
bash scripts/run-docker-oracle-adjudication.sh freeze
~~~

## Reproducibility and reruns

The image defaults to `CODEX_VERSION=0.156.1`, the current Codex CLI release when this harness was frozen. The exact installed version is recorded in `coordinator/codex-version.txt`, and A/B use the same built image. Override `CODEX_VERSION` only deliberately; changing it after A/B begin would invalidate the matched adjudicator runtime.

For a pinned rebuild:

~~~bash
export CODEX_VERSION=<deliberately selected exact npm package version>
bash scripts/run-docker-oracle-adjudication.sh build
~~~

The launcher refuses to overwrite an existing adjudication output. A deliberate rerun requires:

~~~bash
export ADJUDICATION_RERUN=1
~~~

A new independent adjudication study should normally use a new runtime root rather than overwrite a completed pass.

To replace an existing prepared root before adjudication has begun:

~~~bash
export ADJUDICATION_FORCE=1
bash scripts/run-docker-oracle-adjudication.sh prepare-ab
~~~

## Security boundary

The harness provides process/filesystem separation on one Docker host, not protection against a malicious Docker daemon or root user.

The model-provider credential necessarily exists in the Codex process environment when the configured provider requires it. Therefore use a narrowly scoped provider/load-balancer credential for adjudication. Do not place unrelated credentials in the env file.

The strongest practical setup on one Debian machine is:

- one minimal provider config;
- one narrowly scoped Codex provider credential;
- three fresh ephemeral Codex sessions;
- separate A/B/C bind mounts;
- no repository mount;
- no treatment artifacts;
- no TypeSafe key;
- no Docker socket;
- optional restricted-egress Docker network.
