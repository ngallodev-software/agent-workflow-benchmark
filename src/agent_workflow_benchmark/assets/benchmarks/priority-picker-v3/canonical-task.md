# Priority Picker v3 — BM5 canonical task

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

## Corrected v2 determinism requirements

Unsupported sort keys or directions must raise `BacklogValidationError`. Public functions must not mutate caller-owned item dictionaries or input sequences. Decimal numeric values are valid within the frozen 1-through-5 range and scores are rounded to four decimal places.


## BM5 product-interface requirements

These requirements are part of the task, not optional polish.

### Explainability on hover and focus

Each scoring factor shown in a ranked item must expose a concise explanation of what the factor means. The same explanation must be available by mouse hover and keyboard focus; do not make explanatory content hover-only.

Use these stable hooks:

- each help trigger: `data-testid="factor-help"` and `data-factor="impact|urgency|effort|confidence|risk"`;
- the visible explanatory element: `role="tooltip"` and `data-testid="factor-tooltip"`.

The five factor explanations must be reachable without opening developer tools.

### Visual hierarchy and styling

The interface must visibly communicate priority rather than render a flat undifferentiated list.

- Provide a distinct summary strip with `data-testid="summary-strip"`.
- Group the filters/search/sort controls in `data-testid="control-panel"`.
- Each visible score must use `data-testid="priority-score"`.
- Each status indicator must use `data-testid="status-badge"` and visually distinguish at least three statuses present in the supplied fixture.
- The top three ranked items must be visually distinguishable from lower-ranked items and expose `data-priority-tier="top"`.
- The selected/detail item must have a visible selected state in addition to an accessible state such as `aria-selected="true"`.
- Desktop, tablet, and mobile layouts must remain usable without horizontal page overflow; controls must wrap/stack rather than become clipped.

### Interaction feedback

After a successful export, show a visible, non-modal status message using `data-testid="export-status"`. It must identify that JSON was exported and remain visible long enough for deterministic capture.

### Debug/observability switch

Provide a debug switch/button using `data-testid="debug-toggle"`. Debug mode must be off by default and must not alter ranking, filtering, sorting, export output, or normal application behavior.

When enabled, show `data-testid="debug-panel"` with deterministic, human-readable runtime information and these machine-readable hooks:

- `data-testid="debug-bound-controls"`: enumerate all bound interactive controls by test ID, including search, status, risk, sort, export, item-detail interaction, and the debug toggle itself;
- `data-testid="debug-data-request"`: expose the data source/request endpoint, most recent request status, request count, and loaded item count through text plus `data-source`, `data-status`, `data-request-count`, and `data-item-count` attributes;
- `data-testid="debug-state"`: expose current search, status filter, risk filter, sort key/direction, and selected item through `data-search`, `data-status-filter`, `data-risk-filter`, `data-sort`, and `data-selected-id`;
- `data-testid="debug-errors"`: expose the current client error count through `data-count` and render either the recent errors or an explicit "none" state.

The panel must update after a control change and after the initial data request. It is an application observability surface, not a browser-devtools substitute.
