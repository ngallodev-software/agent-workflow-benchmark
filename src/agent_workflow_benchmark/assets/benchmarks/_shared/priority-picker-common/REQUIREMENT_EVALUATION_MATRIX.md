# Priority Picker v1 frozen requirement-to-evaluation matrix

This matrix is frozen for benchmark version `1.0.0`. Changes require a new benchmark version and invalidate direct comparison with earlier runs.

| Requirement | Visible acceptance | Hidden/machine evidence | Points | Visual/human evidence |
|---|---|---|---:|---|
| Exact priority formula | Public formula examples | Decimal and integer inputs, effort floor | 10 of hidden 45 | Rank emphasis |
| Deterministic ordering | Public tie case | score/urgency/impact/id tie chain | 5 of hidden 45 | Rank clarity |
| Strict validation | Public malformed case | types, ranges, duplicate IDs | 8 hidden + 4 robustness | Invalid state presentation |
| Empty and scale behavior | Empty list visible | 1,000-item timing and stable result | 6 robustness | Empty state |
| Search/filter/sort | Named visible controls | Python functions and browser interaction | 12 hidden | Interaction clarity |
| Detail and export | Detail and download controls | JSON ordering and DOM interaction | 8 hidden | Affordances and focus |
| Responsive interface | Three frozen viewports | overflow and DOM checks | 4 accessibility | 15-point human dimension |
| Keyboard/accessibility | Persistent labels and keyboard operation | labels, focus, keyboard detail, console | 10 accessibility | Interaction clarity |
| Scope/completeness | Required files and docs | Git scope, required artifacts, no dependencies | 10 | Not scored separately |
| Engineering quality | Tests and concise docs | compile, public tests, no TODO/stubs, formula docs | 10 | Visible polish only |

Machine allocation is exactly 100 points: hidden functional 45, public regression 15, robustness 10, accessibility/deterministic UI 10, scope/completeness 10, and engineering quality 10. Efficiency is reported separately.

Allowed writes are `README.md`, `BENCHMARK_PLAN.md`, `priority_picker/`, and `tests/`, plus declared disposable cache trees. The supplied `data/backlog.json` is immutable. External dependencies, persistence, authentication, analytics, network integrations, and build systems are explicit non-targets.
