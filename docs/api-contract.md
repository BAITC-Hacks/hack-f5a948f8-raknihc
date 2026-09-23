# Career Quest Integration Contracts

## 1. HTTP API Contract

Статус: первая реализация для `feat/app-ui`; контракт предложен для интеграции
с участником AI engine. Источник точных типов — `backend/app/schemas.py`,
машиночитаемая схема HTTP — `/openapi.json`. Префикс API — `/api/v1`.

### Данные и хранение

Профили, каталог и история имеют поля стартового датасета. JSON-обёртки
`employees`, `events`, `skills`, `role_profiles`, `proficiency_scale` сохраняются
при импорте. Пустые CSV-значения превращаются в `null`, числа — в числа.
`profile.skills` всегда означает оценку на `last_review_date`: после выполнения
она не перезаписывается, иначе движок повторно прибавит историю после оценки.
Новые выполнения записываются в историю с точной `completed_at` и отдельным
результатом симуляции. Транзакция сохраняет историю и результат вместе.

Расчётная дата берётся из `CQ_AS_OF_DATE` (по умолчанию `2026-10-01`).
Реальное UTC-время записи и расчётная дата выполнения хранятся отдельно.
Исходные файлы читаются только при явном запуске CLI импорта; каждый вызов
движка получает свежий снимок SQLite, включая новые выполнения.

### HTTP

| Метод и путь | Результат |
| --- | --- |
| `GET /health` | Состояние БД, режим движка, дата среза |
| `GET /api/v1/employees?offset=0&limit=50` | `{items: Employee[], total, offset, limit}` |
| `GET /api/v1/employees/{id}` | Профиль последней оценки |
| `GET /api/v1/employees/{id}/history` | `{items: HistoryRecord[]}` |
| `GET /api/v1/events` | `{items: Event[]}` |
| `GET /api/v1/skills` | Каталог навыков и требования ролей |
| `GET /api/v1/employees/{id}/recommendations` | `RecommendationResponse` |
| `POST /api/v1/employees/{id}/simulations` | `SimulationResponse`; тело `{event_id, session_date?: date}` |
| `POST /api/v1/employees/{id}/completions` | `CompletionResponse`; тело как у симуляции, обязателен заголовок `Idempotency-Key` |
| `GET /api/v1/employees/{id}/completions` | `{items: Completion[]}` |

Пагинация сотрудников: limit 1–200, offset >= 0. Неизвестные поля входных
моделей запрещены. Ошибки: `{detail: {code, message}}`; ошибки схемы FastAPI —
стандартный `detail[]` и HTTP 422. Неизвестный сотрудник/мероприятие — 404,
невозможное выполнение/повтор — 409, недоступный движок — 503.

Первое выполнение — HTTP 201, повтор того же ключа и тела — HTTP 200 и
сохранённый результат (`replayed: true`). Тот же ключ с другим телом — 409.
Ключ действует в пределах сотрудника, длина 1–128 символов.
Новый ключ для уже выполненного события — 409. Для `EV_036` повторы допустимы
в разные даты сессий; одна сессия не выполняется дважды. Будущую сессию можно
симулировать, но завершить можно только в расчётную дату этой сессии.
Для `self_paced` `session_date` должен отсутствовать.

### Интерфейс движка

`backend/app/engine_port.py` определяет синхронный `Engine` Protocol:

- `recommend(context: EngineContext) -> RecommendationResponse`
- `simulate(context: EngineContext, request: ActivityRequest) -> SimulationResponse`

`EngineContext`: `profile`, `history`, `events`, `catalog`, `as_of_date`.
Реальная реализация живёт в `backend/app/engine/`, приложение подключает её
через `create_app(settings, engine=...)`. Движок не открывает SQLite и не пишет
файлы. API не реализует формулы роста, дефицитов или ранжирования.

`RecommendationResponse`: `employee_id`, `as_of_date`, `mode` (`mock`/`live`),
`current_skills`, `progress_pct` (число или null), `items`, `message`.
Карточка: `event_id`, `title`, `format`, `duration_hours`, `session_date`,
`reasons[]`, `score` (число или null).

`SimulationResponse`: `employee_id`, `event_id`, `as_of_date`, `session_date`,
`mode`, `skills_before`, `skills_after`, `progress_before_pct`,
`progress_after_pct`, `message`. `Completion` хранит этот результат целиком
вместе с `completion_id`, `employee_id`, `event_id`, `session_date`,
`completed_on`, `created_at`, `history_record_id`.

### Поведение mock

`mode: mock` виден во всех ответах движка и сохранённых результатах.
Простая заглушка выбирает до трёх событий в порядке каталога с базовой проверкой
роли, грейда, prerequisites, завершений и расписания. Это не ранжирование.
Навыки возвращаются из профиля без восстановления истории; симуляция сохраняет
их неизменными. Проценты и score равны null. Сохранение выполнения действительно
меняет историю и исключает завершённое событие из последующих mock-рекомендаций.
Никакой LLM или числовой модели развития пока нет.

### Граница текущего этапа

Авторизация сотрудник/HR, UI и HTTP-импорт — следующие задачи. Сейчас API
предназначен для локальной разработки и запускается на `127.0.0.1`.
Открывать этот backend публично до реализации разграничения доступа нельзя.
Доска планирования — отдельный сервис и к этому API не относится.

## 2. AI Engine Python Contract

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

### Inputs

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

### Exact response schema

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

### Field semantics

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

### Failure and ownership boundaries

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

### Example and verification

[Complete E0002 response, limit=1, deterministic mode](integration-example.json).
The runner-up remains EV_036 although only one recommendation is returned.

Run `python -m unittest discover -s tests -q`: 48 tests pass, including six wrapper
integration tests, strict JSON serialization, missing-key fallback, source mapping,
empty results, null next grade, preservation of frozen ranking/score, and the full
200-profile dataset validation. Existing 42 tests remain intact.

## 3. Integration Mapping

An application-layer adapter is required and is NOT implemented by this merge.
`backend/app/engine/` remains frozen. The HTTP and Python schemas above are separate
contracts, not interchangeable versions of the same response.

| Application / HTTP | AI Engine Python | Adapter responsibility |
| --- | --- | --- |
| `Engine.recommend(context)` | `recommend(employee, history, events, catalog, as_of_date, ...)` | Unpack EngineContext; serialize Pydantic objects in JSON mode and dates as ISO strings |
| `context.profile` | `employee` | Preserve the assessment snapshot and supported dataset fields |
| `items` | `recommendations` | Map fields explicitly; current HTTP schema does not expose all AI fields |
| `score`, `reasons[]` | `final_score`, `score_breakdown`, `why_this`, `why_not`, `explanation` | Preserve verified explanations; agree any HTTP schema extension before implementation |
| `current_skills`, `progress_pct` | `readiness_before`; reconstructed skills are available through existing `analyze` | Do not substitute stored assessment skills for current skills; do not recalculate gains in the adapter |
| `format`, `duration_hours`, `session_date` | Event catalog and available-session facts | Supply required HTTP fields and validate session selection in the application layer |
| `mode: mock/live` | `explanation_source: deterministic/llm` | Engine mode and explanation source are different concepts |
| `Engine.simulate(context, request)` | Existing `simulate(employee, history, events, catalog, as_of_date, event_id)` | Adapt simulation output and add context/session metadata expected by SimulationResponse |

The HTTP layer currently defaults to MockEngine. Initial real-engine integration
must use `use_llm=False`. Recording completions, transactions, idempotency and
employee/HR authorization belong to the application layer.

Before enabling the adapter, test `date` versus `completed_at`, self-paced completion
history, session dates, no-candidate responses and duplicate completion. The frozen
engine uses the existing dataset date semantics; no new completion-date handling is
introduced here. Full jury import into an existing database remains pending.
