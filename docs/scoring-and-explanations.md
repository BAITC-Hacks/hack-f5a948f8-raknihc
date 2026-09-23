# Recommendation engine: scoring, evidence and optional wording

## Dataset review and exact formula

The supplied dataset has 106 same-role career goals, 28 role-change goals and 66
profiles with no goal. Goals specify an exact role/grade, mapped only to an existing
`role_profiles` entry. No profession or skill mapping is inferred from event titles.
Activity durations range from 2 to 40 hours.

For each eligible candidate:

```
G = sum of capped skill-gap reductions toward the chosen target
Ct = capped reduction of critical gaps in the chosen target
Cn = capped reduction of critical gaps in the current role's next grade
C = max(Ct, Cn)
H = -negative / max(1, similar_count) + 0.1 * min(completed, 3)
Q = 0.5 * min(1, G / 3), if an explicit goal maps to the target and G > 0; else 0
E = 0.2 * min(1, (G + 2*C) / duration_hours), if duration > 0; else 0
score = G + 2*C + H + Q + E
```

Each reduction is `min(after, required) - before`, only where `before < required`
and the activity actually increases the skill. Similar history means overlapping
developed skills in the last 30 history records, through the calculation date.
Negative statuses: no_show, declined, dropped. Missing history gives H=0.
History is a bounded modifier, never a hard exclusion for previous skips/refusals.

Components and total are rounded to six decimal places; the total is the rounded sum
of reported components. `score_breakdown` exposes `gap_impact=G`,
`critical_gap_impact=2*C`, `history_modifier=H`, `career_goal_modifier=Q`,
`efficiency_modifier=E`, `final_score`. `score_components` retains the more detailed
history penalty/completion bonus for compatibility. Ties use duration, then event ID.

Critical impact is counted using max, not a sum, to avoid double counting the same
next-grade/goal requirement. A critical next-grade activity remains eligible even
when it does not help an explicit role-change goal; that candidate's career-goal
status is `not_applicable` and Q=0. All other eligibility restrictions still apply.
Career goals influence the primary target gaps and the bounded Q bonus. We deliberately
make the goal bonus <=0.5 and efficiency <=0.2, below one critical-unit bonus of 2.
This is an explicit heuristic, not a fitted or experimentally validated outcome model.

`factors.career_goal.status` is `applied`, `unavailable` (no goal), or
`not_applicable` (no improvement toward that goal). Scoring can report `unmapped`
for a mismatched target, but the public engine rejects a non-existent role profile
with ValueError before scoring, preserving the existing input-validation contract.
It does not invent a substitute mapping.

Readiness is skill coverage, not a probability or guarantee of promotion:
`100 * sum(min(level, required)) / sum(required)`. Critical gaps remain separately
visible. Each candidate is simulated independently, not as a cumulative plan.

## Critic

The critic recomputes expected event gains, gaps, score and history from source facts.
It checks completed-event exclusion as well as role/grade, prerequisites and sessions.
Output: `passed`, `evidence_categories`, `warnings`, `errors`, and compatibility fields
`independent_factors` / `factor_count`.

Categories: requirement/skill gap; criticality/career relevance; participation;
actual event gain; eligibility/prerequisites/availability. Requirements and criticality
share one independence group because they come from the same role profile; field
names are not counted as independent factors. At least three groups must pass.
Missing similar history is marked unavailable, produces a warning, and is not counted
or invented. A failed critic raises a calculation error before explanation.

## Optional OpenAI SDK explanation

Default: `analyze(..., use_llm=False)` is fully offline. To opt in, install
`backend/app/engine/requirements-llm.txt`, provide `OPENAI_API_KEY` in the process
environment and call `analyze(..., use_llm=True)`. No `.env` file is read.
`OPENAI_MODEL` optionally overrides `gpt-4.1-mini`.

Only the already-selected top recommendation gets an optional `explanation_card`;
all candidates retain deterministic explanations. The second-best candidate is
included even with `limit=1`. No names, employee IDs or full employee profiles are sent.
Payload includes the verified role/grade, mapped requirements, relevant gaps, event
impact, history evidence, readiness, score breakdown, runner-up and critic result.

The LLM is deliberately a constrained editorial layer: it chooses among fact-derived
wording variants for five card fields. JSON Schema enums plus local exact-value
validation prevent arbitrary invented prose, event selection or arithmetic. This
limits writing variety, but avoids pretending a general text validator proves truth.
Fields: explanation, why_this, why_not, expected_career_impact, caution.

Uses the official Python SDK directly, Responses API, `store=False`, a 5-second SDK
network timeout and zero retries. Network timeout is not an end-to-end latency guarantee.
Missing key/SDK, API errors, timeouts, refusals, incomplete or ungrounded outputs all
return a deterministic card. Error strings and keys are never logged or returned.
The exception fallback uses a fixed reason code.

SDK/schema reference: [official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## Verification

Run `python -m unittest discover -s tests -v` from the repository root.
42 tests passed, including all original 12, schema-compatible jury fixtures A–G,
critic tampering and mocked LLM failure/success paths. Dataset test checks every
profile and candidate and skips only when local data is not supplied.

Full run: 200 profiles, 476 candidates, 35 employees without a valid candidate.
Source files matched the original ZIP byte-for-byte. Reports:
[engine-validation.json](engine-validation.json), [engine-examples.json](engine-examples.json).
No live API response was obtained: OPENAI_API_KEY is absent in the execution environment.

## Last-review snapshot regression checks

Nine dedicated state-builder tests pass: before/on/after review, multiple distinct
post-review completions in chronological order, event cap, preservation above cap,
repeatable completions across the review boundary, future records and incomplete
activities. No production logic change was needed. Only completed rows strictly
after the review and through as_of_date contribute. Formula:
`max(old, min(5, max_level, old + gain))`. The event cap limits new growth; an
already-higher skill is preserved. For self-paced records, enrollment date remains
an explicit proxy because the dataset does not contain a completion timestamp.
