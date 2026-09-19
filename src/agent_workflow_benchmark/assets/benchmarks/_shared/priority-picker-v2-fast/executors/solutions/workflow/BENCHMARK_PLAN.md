# Priority Picker implementation plan and evidence

## Requirements map

- `priority_picker/priority.py`: strict schema/range/duplicate validation, exact score, deterministic ranking, filtering, sorting, export, and JSON loading.
- `priority_picker/web/`: labeled controls, ranked cards, detail, export, error/empty states, keyboard focus, and desktop/tablet/mobile layouts.
- `tests/public/`: preserve and extend focused public behavior checks.
- `README.md`: exact formula and local run instructions.

## Verification

Verify the implementation with:

- `python -m unittest discover -s tests/public -v`
- `python -m compileall -q priority_picker tests`
- Local browser exercise of search, filters, sort, keyboard item activation, detail, export, empty state, and required viewports.

## Scope and non-targets

Only the two root Markdown files plus `priority_picker/` and `tests/` are writable. `data/backlog.json` is immutable. No dependencies, framework, persistence, authentication, analytics, or unrelated architecture are introduced.
