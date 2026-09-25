FROM node:24-bookworm-slim

ARG CODEX_VERSION=0.156.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && codex --version \
    && npm cache clean --force

COPY docker/adjudication/entrypoint.sh /usr/local/bin/aw-adjudicate
COPY docker/adjudication/wrap-output.mjs /opt/aw-adjudication/wrap-output.mjs

RUN mkdir -p /run/adjudication \
    && chmod 0555 /usr/local/bin/aw-adjudicate \
    && chmod 0444 /opt/aw-adjudication/wrap-output.mjs

WORKDIR /input
ENTRYPOINT ["/usr/local/bin/aw-adjudicate"]
