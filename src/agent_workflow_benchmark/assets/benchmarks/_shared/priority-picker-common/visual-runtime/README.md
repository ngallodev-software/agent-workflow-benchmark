# Publication visual runtime

The development lock verifies exact Playwright and Chromium versions plus the resolved font files. Publication claims additionally require an immutable OCI image reference, the browser executable digest, and every font digest.

Build with a digest-qualified base image:

```bash
docker build \
  --build-arg PLAYWRIGHT_IMAGE='mcr.microsoft.com/playwright/python:v1.57.0-noble@sha256:<verified-digest>' \
  -t priority-picker-benchmark-runtime:local \
  visual-runtime/
```

Run `agent-workflow benchmark runtime-seal` **inside that image**, passing the same digest-qualified image reference. The command resolves and hashes Chromium and all fonts declared in `visual-runtime-lock.json`, then writes a publication lock. `benchmark runtime-attest --claim-level publication` independently verifies the resulting lock before capture or publication.

A tag-only image is intentionally rejected. The repository does not publish a fabricated digest because the digest must identify the exact image built or pulled by the operator.
