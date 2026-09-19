# Supply an immutable Playwright image, for example:
# docker build --build-arg PLAYWRIGHT_IMAGE='mcr.microsoft.com/playwright/python:v1.57.0-noble@sha256:<digest>' ...
ARG PLAYWRIGHT_IMAGE
FROM ${PLAYWRIGHT_IMAGE}

ENV LC_ALL=C LANG=C LANGUAGE=C TZ=UTC
WORKDIR /benchmark

# Fail the build if the expected browser and fonts are absent. The runtime lock
# itself is sealed from inside the built image with `benchmark runtime-seal`.
RUN python -c "import importlib.metadata; assert importlib.metadata.version('playwright') == '1.57.0'" \
 && test -x /usr/bin/chromium \
 && find /usr/share/fonts -name Arimo-Regular.ttf -print -quit | grep -q . \
 && find /usr/share/fonts -name DejaVuSans.ttf -print -quit | grep -q .
