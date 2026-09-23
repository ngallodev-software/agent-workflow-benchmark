# Change Window Planner

Build a small Python + browser application that turns a service dependency graph into a deterministic deployment plan for a fixed maintenance window.

The supplied repository is intentionally incomplete. Use only the Python standard library and browser-native HTML/CSS/JavaScript. Do not add third-party dependencies or change the supplied input data.

## Data contract

`data/change-set.json` contains:

- `window.duration_minutes`: positive integer maintenance-window capacity.
- `window.parallelism`: positive integer maximum services per deployment wave.
- `services`: a list of service objects.

Each service must contain:

- `id`: non-empty unique string.
- `name`: non-empty string.
- `owner`: non-empty string.
- `duration_minutes`: integer from 1 through 240.
- `risk`: one of `low`, `medium`, `high`.
- `status`: one of `ready`, `blocked`.
- `dependencies`: list of unique service IDs.

Reject malformed roots, duplicate IDs, missing dependencies, self-dependencies, duplicate dependency references, unsupported risk/status values, invalid durations, and dependency cycles with `ChangeWindowValidationError`.

Public functions in `change_window.planner`:

- `validate_change_set(value) -> dict`
- `dependency_closure(services, service_id) -> list[str]`
- `dependent_closure(services, service_id) -> list[str]`
- `plan_waves(services, *, parallelism, selected_ids=None) -> list[list[str]]`
- `estimate_minutes(services, waves) -> int`
- `build_change_plan(value, *, selected_ids=None) -> dict`
- `filter_services(services, *, query="", owner="all", risk="all", status="all") -> list[dict]`
- `load_change_set(path) -> dict`

## Planning rules

`plan_waves` and `build_change_plan` must be deterministic.

- A service may not appear before any selected dependency.
- When a selected service depends on an unselected service, automatically include that dependency and its transitive dependencies.
- Blocked services may be present in data but must not be scheduled. If a requested service is blocked, include it in `blocked_selected` and do not schedule it.
- Each wave contains at most `parallelism` services.
- Among currently eligible services, order by risk severity `high`, `medium`, `low`, then descending duration, then service ID.
- Pack each wave from that ordering up to the parallelism limit.
- `estimate_minutes` is the sum of the longest service duration in each wave.
- `build_change_plan` returns at least:
  - `waves` with 1-based wave number, service IDs, wave duration, and risk counts;
  - `scheduled_ids`;
  - `blocked_selected`;
  - `estimated_minutes`;
  - `window_minutes`;
  - `within_window`;
  - `parallelism`;
  - `service_count`.
- Empty selections are valid and produce an empty plan with zero estimated minutes.
- Do not mutate caller-owned objects.

## Browser application

Replace the placeholder page with a usable Change Window Planner.

The page must load `/api/plan` and render the supplied service data and computed waves. Include:

- summary strip with total services, ready count, blocked count, estimated minutes, and whether the plan fits the window;
- labeled search, owner, risk, and status controls;
- a deployment-wave view with every scheduled service in its assigned wave;
- visually distinct low/medium/high risk and blocked states;
- service selection/details showing direct dependencies, transitive dependencies, and transitive dependents;
- clear window-overrun warning when `within_window` is false;
- JSON export of the currently displayed plan;
- non-modal export confirmation at `data-testid="export-status"`;
- empty and request/error states;
- keyboard-operable service cards/details and visible focus styling.

Required hooks:

- `data-testid="change-window-app"`
- `data-testid="summary-strip"`
- `data-testid="control-panel"`
- `data-testid="search-input"`
- `data-testid="owner-filter"`
- `data-testid="risk-filter"`
- `data-testid="status-filter"`
- `data-testid="deployment-waves"`
- `data-testid="deployment-wave"`
- `data-testid="service-card"`
- `data-testid="service-detail"`
- `data-testid="window-status"`
- `data-testid="export-button"`
- `data-testid="export-status"`

## Debug observability

Add a debug switch at `data-testid="debug-toggle"`, off by default and behavior-neutral.

When enabled, `data-testid="debug-panel"` must expose:

- `debug-bound-controls`: enumerate search, owner, risk, status, export, service detail, and debug toggle;
- `debug-data-request`: source endpoint, latest status, request count, and loaded service count with `data-source`, `data-status`, `data-request-count`, and `data-item-count`;
- `debug-state`: current search/owner/risk/status/selected service;
- `debug-errors`: error count and recent errors or explicit none.

Update debug state after initial load and every relevant control or selection change.

## Responsive and accessibility requirements

The page must remain usable without horizontal page overflow at:

- 1440 × 1000
- 834 × 1112
- 390 × 844

Controls may wrap or stack. Preserve readable wave grouping and service details at all sizes. Use semantic controls and visible labels. Selection must be visible and represented with an accessible state such as `aria-selected`.

## Engineering constraints

- Python standard library only.
- Browser-native HTML/CSS/JavaScript only.
- Do not modify `data/change-set.json`.
- Keep server changes focused.
- Add focused public tests for your implementation.
- Update `README.md` with run/use instructions.
- Maintain `BENCHMARK_PLAN.md` with requirements, commands run, results, remaining uncertainty, and files changed.
- Do not inspect parent/sibling worktrees, benchmark evaluator material, prior benchmark outputs, or unrelated host files.
