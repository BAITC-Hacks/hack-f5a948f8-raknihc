# Engine integration contract — initial baseline

Python 3.10+, standard library only. Import from `backend.app.engine`.
These are Python functions for the application backend, not HTTP endpoints.

```python
from backend.app.engine import load_dataset, analyze, simulate

data = load_dataset("data/private/career_quest_dataset")
employee = data["employees"][0]
result = analyze(employee, data["history"], data["events"],
                 data["catalog"], data["as_of_date"])
```

`analyze(employee, history, events, catalog, as_of_date, limit=3)` takes
the dataset employee object, CSV history rows as dictionaries, the events array,
the complete skills.json object, and an ISO date. Imported employees and history
can be passed directly; the engine does not require an employee in the original file.
`limit` is 1–3. Invalid profiles or history references raise `ValueError`.
Full import-schema validation remains to be implemented at the engine boundary.

Returns a JSON-compatible object:

- `employee_id`, `as_of_date`, `mode` (`rules` for this baseline).
- `effective_skills`: skill ID to level.
- `target`: `{role, grade}`; absent career goal defaults to next grade, or current Lead.
- `progress_pct`: capped skill coverage, not a probability of promotion.
- `gaps`: `{skill_id, name, current, required, gap, critical}` objects.
- `critical_gaps`: unresolved critical skill IDs.
- `recommendations`: up to three `{event_id, title, score, next_session,
  duration_hours, facts, explanation, progress_after_pct}` objects.
- `facts`: current/target role and grade, `skill_changes` with before/after/required/
  critical fields, and counts of similar activity history.
- `excluded_events`: event IDs and machine-readable exclusion reasons.
- `no_recommendation_reason`: null or `no_eligible_gap_closing_event`.
- `warnings`: calculation assumptions or ignored repeat completions.

`simulate(employee, history, events, catalog, as_of_date, event_id)` returns
`event_id`, `skills_before`, `skills_after`, `progress_before_pct`,
`progress_after_pct`. It accepts eligible development events, including candidates
outside the top three. It neither writes history nor awards points. The application
owns transactions, authorization, completion dates and idempotency. Already completed
non-repeatable events are rejected. Mandatory learning needs a separate application flow.

## Algorithm and limitations

Only completed history after the last review contributes skill gains. For self-paced
activities the dataset lacks completion timestamps: enrollment date is used as a proxy,
and a warning is returned. The initial dataset snapshot is 2026-10-01.
Older completed activities still prevent duplicate recommendations. Gains never reduce
an existing level; the event cap and the global maximum of 5 are respected.

Eligibility uses current role and grade, prerequisites, completion, in-progress status,
future sessions and positive target-gap gains. A career change does not override current
audience restrictions. Mandatory activities are excluded.

Score = gap reduction + 2 × critical gap reduction − negative participation fraction
+ 0.1 × min(similar completions, 3). Similar means overlapping developed skills,
considering the employee's last 30 history records. Negative statuses are no_show,
dropped and declined. Ties favor shorter activities then event ID. This is an explicit
heuristic baseline; no LLM is connected yet. Explanations quote computed facts only.

Next work: complete schema validation, LLM integration with verified facts and timeout
fallback, HR aggregates and additional edge-case tests. API, UI, storage and permissions
belong to the application participant.

## Local checks

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

Place the seven files from the supplied dataset in `data/private/career_quest_dataset`.
That directory is ignored by Git; the tests use independent synthetic fixtures.
