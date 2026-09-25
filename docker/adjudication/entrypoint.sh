#!/bin/sh
set -eu

umask 077

: "${ADJUDICATOR_ID:?ADJUDICATOR_ID is required}"
: "${EXPECTED_VIEW_SHA256:?EXPECTED_VIEW_SHA256 is required}"
: "${CODEX_HOME:=/tmp/codex-home}"
: "${HOME:=/tmp/home}"

if env | grep -Eq '^TYPESAFE_[A-Za-z0-9_]*='; then
    echo "refusing adjudicator startup: TYPESAFE_* credentials must not enter blinded oracle containers" >&2
    exit 64
fi

for required in \
    /input/oracle-view.json \
    /input/oracle-protocol.md \
    /input/START_PROMPT.md \
    /input/model-output.schema.json \
    /input/pass-metadata.json \
    /run/adjudication/config.toml
do
    if [ ! -r "$required" ]; then
        echo "missing required adjudication input: $required" >&2
        exit 66
    fi
done

actual_view_sha256="$(sha256sum /input/oracle-view.json | awk '{print $1}')"
if [ "$actual_view_sha256" != "$EXPECTED_VIEW_SHA256" ]; then
    echo "oracle view SHA-256 mismatch: expected $EXPECTED_VIEW_SHA256, got $actual_view_sha256" >&2
    exit 65
fi

mkdir -p "$HOME" "$CODEX_HOME"
cp /run/adjudication/config.toml "$CODEX_HOME/config.toml"
chmod 0600 "$CODEX_HOME/config.toml"

codex --version > /output/codex-version.txt

prompt="$(cat /input/START_PROMPT.md)"

set +e
codex exec \
    --ephemeral \
    --skip-git-repo-check \
    --ignore-rules \
    --sandbox read-only \
    --config 'approval_policy="never"' \
    --config 'web_search="disabled"' \
    --config 'sandbox_workspace_write.network_access=false' \
    --output-schema /input/model-output.schema.json \
    -o /output/model-output.json \
    "$prompt" \
    > /output/codex.stdout.log \
    2> /output/codex.stderr.log
status=$?
set -e

if [ "$status" -ne 0 ]; then
    echo "codex adjudication failed with exit code $status; inspect /output/codex.stderr.log" >&2
    exit "$status"
fi

node /opt/aw-adjudication/wrap-output.mjs
sha256sum /output/adjudication.json > /output/adjudication.json.sha256
