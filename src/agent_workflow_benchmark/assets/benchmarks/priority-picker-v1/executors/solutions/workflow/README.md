# Priority Picker

A dependency-free Python and browser application that validates a synthetic backlog, computes the frozen priority score, and presents a searchable, filterable, responsive ranking.

```text
score = round((2*impact + 1.5*urgency + confidence + 0.5*risk) / max(effort, 1), 4)
```

Run `python -m unittest discover -s tests/public -v`, then launch `python -m priority_picker.server --port 8000` and open `http://127.0.0.1:8000`.
