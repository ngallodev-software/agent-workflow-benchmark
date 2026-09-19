# Priority Picker Fast v1 — canonical repair task

Repair and verify the supplied dependency-free Priority Picker application. The implementation is intentionally almost complete; keep the existing architecture and make only bounded changes.

Required contract:

- `score = round((2*impact + 1.5*urgency + confidence + 0.5*risk) / max(effort, 1), 4)`;
- deterministic ranking by score descending, urgency descending, impact descending, then ID ascending;
- validation rejects malformed values, duplicate IDs, unsupported statuses, sort keys, and sort directions;
- search covers ID, title, and description and composes with status/risk filters;
- export preserves the displayed ranked order;
- the live dashboard remains responsive, keyboard operable, visibly focused, labeled, and downloadable;
- no dependencies, build system, network service, or changes to `data/backlog.json`.

Run `python -m unittest discover -s tests/public -v`, retain a concise `BENCHMARK_PLAN.md`, and update `README.md` with run/test instructions. The model execution phase has a hard 150-second target and is designed to complete in under three minutes of wall time.
