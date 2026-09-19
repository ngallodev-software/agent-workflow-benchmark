# Priority Picker v1 — canonical task

Implement a small, dependency-free web application that reads `data/backlog.json`, computes a deterministic priority score for each item, and presents the ranked backlog as a polished responsive dashboard.

## Required behavior

Each backlog item has these required fields:

- `id`: non-empty unique string
- `title`: non-empty string
- `impact`, `urgency`, `effort`, `confidence`, `risk`: numeric values from 1 through 5
- `status`: one of `planned`, `ready`, `in_progress`, or `blocked`
- `description`: string

The score is frozen as:

```text
score = round((2*impact + 1.5*urgency + confidence + 0.5*risk) / max(effort, 1), 4)
```

Default ranking is score descending, then urgency descending, impact descending, then `id` ascending. Duplicate IDs and malformed records must be rejected with a useful error. Empty input is valid. Ranking 1,000 valid items must complete comfortably within two seconds on the benchmark host.

The Python module `priority_picker.priority` must expose:

- `calculate_priority(item)`
- `validate_items(items)`
- `rank_items(items)`
- `filter_items(items, query="", status="all", risk="all")`
- `sort_items(items, key="priority", direction="desc")`
- `export_ordering(items, destination)`
- `load_backlog(path)`

## User interface

The page must include:

- a clear title and summary counts;
- search, status filter, risk filter, and sort controls with persistent visible labels;
- a ranked list with rank, title, score, status, and the five scoring factors;
- item detail interaction showing the description and complete factor breakdown;
- an export control that downloads the current ordering as JSON;
- useful empty and invalid-data states;
- keyboard-operable controls and item detail interaction;
- no horizontal page overflow at 1440×1000, 834×1112, or 390×844;
- responsive behavior appropriate to desktop, tablet, and mobile.

Use these stable hooks for deterministic capture: `priority-app`, `search-input`, `status-filter`, `risk-filter`, `sort-control`, `priority-list`, `priority-item`, `item-detail`, and `export-button` as `data-testid` values.

## Constraints

Use only the Python standard library and browser-native HTML/CSS/JavaScript. Do not add network services, package-manager dependencies, build systems, analytics, authentication, persistence, or unrelated abstractions. Keep `data/backlog.json` unchanged. Add or update focused public tests and concise `README.md` instructions. Write the phase-one plan to `BENCHMARK_PLAN.md`.
