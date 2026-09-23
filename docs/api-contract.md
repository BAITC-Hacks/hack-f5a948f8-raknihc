# AI Engine application contract

The application developer should call one entry point:

```python
from backend.app.engine import recommend

response = recommend(
    employee, history, events, catalog, as_of_date,
    limit=3, use_llm=False,
)
```

Exact signature:
`recommend(employee, history, events, catalog, as_of_date, *, limit=3, use_llm=False) -> dict`.
This is a Python function, not an HTTP endpoint. Python 3.10+.
The recommendation algorithm is frozen. This boundary only maps existing outputs.
Legacy `analyze`, `simulate`, and `load_dataset` imports remain available.

## Inputs

- `employee`: one profile object from `employees.json["employees"]`, or an imported
  profile with the same schema. It need not occur in the original dataset.
- `history`: list of dictionaries matching activity_history.csv. All employees may
  be included; the engine filters by employee_id. CSV string values are supported.
- `events`: `events.json["events"]`, a list of event dictionaries.
- `catalog`: complete skills.json object, including skills and role_profiles.
- `as_of_date`: ISO date string YYYY-MM-DD. Use 2026-10-01 for the supplied snapshot.
- `limit`: integer 1, 2 or 3. Fewer results, including zero, are valid when candidates
  are unavailable. The engine never relaxes eligibility to fill the list.
- `use_llm`: bool, default False. True attempts optional wording for the top candidate
  only; other recommendations retain deterministic wording.

The wrapper does not read files, environment keys, or databases itself. An enabled
LLM explainer reads OPENAI_API_KEY from the process environment; no .env file is read.
See [scoring-and-explanations.md](scoring-and-explanations.md) for SDK installation.

Example local loading (the application may instead supply objects from storage):

```python
import json
from backend.app.engine import load_dataset, recommend

data = load_dataset("data/private/career_quest_dataset")
response = recommend(data["employees"][0], data["history"], data["events"],
                     data["catalog"], data["as_of_date"])
serialized = json.dumps(response, ensure_ascii=False, allow_nan=False)
```

## Exact response schema

The TypeScript notation below describes JSON values only; all fields are required.
`number` values are finite. There are no datetimes, sets, SDK objects or model instances.

```typescript
type Grade = "Junior" | "Middle" | "Senior" | "Lead";
type Trajectory = { role: string; grade: Grade };
type EvidenceGroup = "eligibility" | "target_fit" | "participation" | "activity_impact";
type EvidenceCategory =
  | "eligibility_prerequisites_availability"
  | "requirement_skill_gap"
  | "criticality_or_career_relevance"
  | "participation_history"
  | "actual_event_gain";

type Critic = {
  passed: boolean;
  evidence_categories: Array<{
    category: EvidenceCategory;
    status: "verified" | "unavailable" | "failed";
    independence_group: EvidenceGroup;
  }>;
  warnings: string[];
  independent_factors: EvidenceGroup[];
  factor_count: number;
  errors: string[];
  history_evidence_available: boolean;
};

type Recommendation = {
  event_id: string;
  title: string;
  final_score: number;
  score_breakdown: {
    gap_impact: number;
    critical_gap_impact: number;
    history_modifier: number;
    career_goal_modifier: number;
    efficiency_modifier: number;
    final_score: number;
  };
  skill_impacts: Array<{
    skill_id: string;
    before: number;
    after: number;
    gain: number;
  }>;
  readiness_after: number;
  why_this: string;
  why_not: string;
  alternative_event_id: string | null;
  critic: Critic;
  explanation: string;
  explanation_source: "llm" | "deterministic";
  fallback_reason: "disabled" | "missing_api_key" | "llm_unavailable_or_invalid" | null;
  expected_career_impact: string;
  caution: string;
};

type RecommendationResponse = {
  employee_id: string;
  current_grade: Grade;
  target: Trajectory;
  next_grade: Trajectory | null;
  readiness_before: number;
  recommendations: Recommendation[]; // zero to limit; limit <= 3
  no_recommendation_reason: "no_eligible_gap_closing_event" | null;
  warnings: string[];
};
```

## Field semantics

- `target` is the explicit career goal, or the existing default trajectory.
  `next_grade` is the next grade in the current role; null for Lead or absent profile.
  These can differ for career changes. Readiness measures `target`, in percent 0?100.
- `skill_impacts` contains every skill actually increased in the simulation, including
  skills outside the target requirements. `gain` is the realized increase after caps,
  not the raw event gain. Every candidate starts from the same reconstructed state.
- `final_score` is identical to score_breakdown.final_score and the frozen engine score.
- `why_not` compares the candidate with the next-ranked eligible candidate. For the
  top item this is the second-best option, even when limit=1. For the last eligible
  candidate it states that no alternative exists and alternative_event_id is null.
  This explains the local ranking comparison, not why a lower item beats the top item.
- `explanation_source` maps internal source `openai` to `llm`; fallback is always
  `deterministic`. Only the top candidate can receive an LLM card. `disabled` on
  lower candidates is expected even when use_llm=True.
- A returned recommendation has critic.passed=true. Missing history is a warning,
  not a fabricated fact or an automatic failure. A critic rejection raises ValueError.
- `warnings` preserves state-reconstruction caveats, including self-paced enrollment
  dates used as a proxy for unavailable completion timestamps.

## Failure and ownership boundaries

For valid supported input, no eligible candidate returns an empty list and a reason,
not an exception. Invalid limit, unsupported role/grade target or invalid history
can raise ValueError. Malformed schemas may raise KeyError/TypeError: full import
schema validation is not implemented; the application must validate uploaded input.

Missing API key/SDK, timeout, API error, refusal or invalid LLM output preserves the
recommendation and returns a deterministic explanation. No API exception text or
credentials enter the response. The LLM never changes scores or event selection.

The application owns authorization, persistence and idempotent completion. After
recording a completion, call recommend with updated history and calculation date.
No FastAPI, SQLite or frontend implementation is provided by this engine.

## Example and verification

[Complete E0002 response, limit=1, deterministic mode](integration-example.json).
The runner-up remains EV_036 although only one recommendation is returned.

Run `python -m unittest discover -s tests -q`: 48 tests pass, including six wrapper
integration tests, strict JSON serialization, missing-key fallback, source mapping,
empty results, null next grade, preservation of frozen ranking/score, and the full
200-profile dataset validation. Existing 42 tests remain intact.
