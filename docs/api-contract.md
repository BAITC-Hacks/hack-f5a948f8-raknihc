# Career Quest Integration Contracts

## 1. HTTP API Contract

Source: application contract at `653c6a3`; exact models are in
`backend/app/schemas.py`. The application now defaults to RealAIEngineAdapter; the retained mock behavior
section describes the explicit emergency fallback.

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
Исходный каталог загружается через CLI; HR может добавлять профили и историю через API. Каждый вызов
движка получает свежий снимок SQLite, включая новые выполнения.

### HTTP

| Метод и путь | Результат |
| --- | --- |
| `GET /health` | Состояние БД, режим движка, дата среза |
| `POST /api/v1/auth/login` | `{access_token, token_type, expires_at, user}`; тело `{username,password}` |
| `GET /api/v1/auth/me` | `{user_id, username, role, employee_id}` |
| `POST /api/v1/auth/logout` | 204, сессия отозвана |
| `GET /api/v1/hr/summary` | Общие счётчики сотрудников, истории и выполнений; только HR |
| `GET /api/v1/hr/overview` | `HROverview`: дефициты, сотрудники и статистика мероприятий; только HR |
| `POST /api/v1/hr/imports` | `JuryImportResult`; строки `employees_json?`, `history_csv?`, флаг `dry_run` (по умолчанию true); только HR |
| `GET /api/v1/employees?offset=0&limit=50` | `{items: Employee[], total, offset, limit}` |
| `GET /api/v1/employees/{id}` | Профиль последней оценки |
| `GET /api/v1/employees/{id}/history` | `{items: HistoryRecord[]}` |
| `GET /api/v1/events` | `{items: Event[]}` |
| `GET /api/v1/skills` | Каталог навыков и требования ролей |
| `GET /api/v1/employees/{id}/recommendations` | `RecommendationResponse` |
| `GET /api/v1/employees/{id}/trajectory` | `TrajectoryResponse`: требования цели и дефициты, доступ как к профилю |
| `POST /api/v1/employees/{id}/simulations` | `SimulationResponse`; тело `{event_id, session_date?: date}` |
| `POST /api/v1/employees/{id}/completions` | `CompletionResponse`; тело как у симуляции, обязателен заголовок `Idempotency-Key` |
| `GET /api/v1/employees/{id}/completions` | `{items: Completion[]}` |

Пагинация сотрудников: limit 1–200, offset >= 0. Неизвестные поля входных
моделей запрещены. Ошибки: `{detail: {code, message}}`; ошибки схемы FastAPI —
стандартный `detail[]` и HTTP 422. Неизвестный доступный сотрудник/мероприятие — 404,
невозможное выполнение/повтор — 409. Недоступный движок для preview вызывает
описанный ниже fallback; при выполнении ошибка 503 сохраняется.

Все `/api/v1` маршруты, кроме `/auth/login`, требуют `Authorization: Bearer <token>`.
Нет действующей сессии — 401; нет прав — 403; превышен лимит входа — 429.
Сотрудник читает/симулирует/выполняет только свой профиль. Подмена ID в URL
блокируется до чтения данных и вызова движка (включая несуществующий чужой ID).
HR читает все профили и симулирует активности, но завершает только свои, если
его учётная запись привязана к профилю. Список сотрудников и все `/hr/*` — только HR.
Каталоги доступны обеим ролям. [Полная матрица прав](access-control.md).

Токены непрозрачные, живут по реальному UTC-времени. Frontend отправляет их
в заголовке, сервер не использует авторизационные cookies. Поля роли и employee_id
во входном теле login запрещены; права берутся из SQLite при каждом запросе.

Первое выполнение — HTTP 201, повтор того же ключа и тела — HTTP 200 и
сохранённый результат (`replayed: true`). Тот же ключ с другим телом — 409.
Ключ действует в пределах сотрудника, длина 1–128 символов.
Новый ключ для уже выполненного события — 409. Для `EV_036` повторы допустимы
в разные даты сессий; одна сессия не выполняется дважды. Будущую сессию можно
симулировать, но завершить можно только в расчётную дату этой сессии.
Для `self_paced` `session_date` отсутствует или равен `null`.

### Интерфейс движка

`backend/app/engine_port.py` определяет синхронный `Engine` Protocol:

- `recommend(context: EngineContext) -> RecommendationResponse`
- `simulate(context: EngineContext, request: ActivityRequest) -> SimulationResponse`
- `trajectory(context: EngineContext) -> TrajectoryResponse`

`EngineContext`: `profile`, `history`, `events`, `catalog`, `as_of_date`.
Реальная реализация живёт в `backend/app/engine/`, приложение подключает её
через `create_app(settings, engine=...)`. Движок не открывает SQLite и не пишет
файлы. HTTP-обработчики не реализуют формулы роста, дефицитов или ранжирования.

`RecommendationResponse`: `employee_id`, `as_of_date`, `mode` (`mock`/`live`),
`current_skills`, `progress_pct` (число или null), `items`, `message`.
Карточка: `event_id`, `title`, `format`, `duration_hours`, `session_date`,
`reasons[]`, `score` (число или null), `skill_changes[]`. Количество карточек — 0–3;
пустой список означает отсутствие подходящих шагов, а не ошибку сервера.

`SimulationResponse`: `employee_id`, `event_id`, `as_of_date`, `session_date`,
`mode`, `skills_before`, `skills_after`, `progress_before_pct`,
`progress_after_pct`, `message`, `skill_changes[]`. `Completion` хранит этот результат целиком
вместе с `completion_id`, `employee_id`, `event_id`, `session_date`,
`completed_on`, `created_at`, `history_record_id`.

Оба preview-ответа дополнительно содержат `skills_basis` (`last_review`/`current`),
`assessed_on` (дата или null), `is_fallback` (по умолчанию false), `fallback_reason`
(строка или null). `skill_changes[]`: `{skill_id, name, before, after, gain}` — уровни
0–5, `gain = after - before`. Они есть и в карточках, и в симуляции. Значения до/после
рассчитывает движок; UI не прибавляет навыки самостоятельно. Для совместимости с
ранее сохранёнными выполнениями новые поля имеют значения по умолчанию; пустой
`skill_changes` отображается как неизвестный прирост.

Если `recommend` или `simulate` выбрасывает `DomainError(503, ...)` либо
`TimeoutError`, API повторяет preview на `MockEngine` с тем же контекстом SQLite и
возвращает `mode: mock`, `is_fallback: true` и объяснение. Основной адаптер сам
должен ограничивать время внешнего запроса; API не задаёт ему отдельный deadline.
Ошибки 403/404/409/422, валидация и ошибки программирования не скрываются.
Fallback проверяет доступность события и сессии заново. Для `completions` и
`trajectory` этот механизм не применяется. Frontend прекращает запрос через 15 с
и предлагает повтор; при 401 очищает сессию, при закрытии окна отменяет запрос.

`TrajectoryResponse`: `employee_id`, `as_of_date`, `assessed_on`, `mode`,
`skills_basis` (`last_review`/`current`), `target` (CareerGoal или null),
`status` (`target_set`/`no_goal`/`target_unavailable`), `requirements[]`,
`met_count`, `critical_gap_count`, `progress_pct`, `message`, `current_skills`.
Каждое требование содержит `skill_id`, `name`, `type`, `current_level`,
`required_level`, `gap`, `critical`. Адаптер сравнивает восстановленные по истории
навыки с требованиями явно заданной цели: отсутствие навыка — 0, gap не ниже 0.
`current_skills` содержит все актуальные навыки, в том числе вне цели. В MockEngine
процент готовности неизвестен и без явной цели возвращается no_goal. RealAIEngineAdapter
возвращает рассчитанную готовность и эффективную цель AI; если цель не выбрана
сотрудником, target_source равен automatic и это явно отмечается в интерфейсе.
При смене роли сравнение идёт с целевой ролью; отсутствующий профиль требований
даёт `target_unavailable`. Все расчёты остаются в адаптере движка, не в React.

### Поведение mock

`mode: mock` виден во всех ответах движка и сохранённых результатах.
Простая заглушка выбирает до трёх событий в порядке каталога с базовой проверкой
роли, грейда, prerequisites, завершений и расписания. Это не ранжирование.
Навыки восстанавливаются из профиля и completed-истории после оценки. Для каждого развиваемого
навыка `after = max(before, min(max_level, before + gain))`, отсутствующий навык
имеет `before = 0`. Навык выше потолка мероприятия не снижается. Мероприятия без
положительного прироста исключаются. Объяснения ссылаются на роль/грейд,
развиваемые навыки (критический дефицит цели при наличии) и отсутствие завершения.
Симуляция не пишет в SQLite, проценты и score равны null. Сохранение выполнения
действительно меняет историю и исключает завершённое событие из следующих
рекомендаций, не переписывая исходную оценку. LLM и настоящее ранжирование ещё
не подключены. `skills_basis: current` означает учёт завершений: дата `completed_at`
или, при её отсутствии, `date` должна быть строго после `last_review_date` и не позже
`as_of_date`. Это допущение явно показано в UI. Для повторяемого клуба прирост
учитывается отдельно по дате сессии; обычное добровольное событие — один раз,
обязательное обучение — по датам записей. Старые повторные записи не удаляются.
Обработка идёт по эффективной дате завершения и record_id; повторная история не
начисляется поверх уже изменённого профиля, поскольку исходная оценка не меняется.

### HR и добавочный импорт

`HROverview`: `as_of_date`, `mode`, `employees[]`, `skill_gaps[]`, `events[]`,
`no_step_count`, `unavailable_count`, `message`. В `employees` — ID, имя, отдел,
роль, грейд, `critical_gap_count` (null при неизвестном расчёте),
`recommendation_status` (`available`/`none`/`unavailable`) и `reason`.
Сотрудники упорядочены по ID. Ошибка движка не выдаётся за отсутствие рекомендаций.

`skill_gaps`: ID/имя навыка, `employees_count`, `critical_count`. Счётчики означают
число сотрудников с положительным дефицитом относительно их явно заданной цели.
`events`: ID/название, уникальные `participants`, общее число `records`,
`completed`, `in_progress`, `other`. Каждая сессия/повторная запись учитывается отдельно.
Один запрос читает согласованный снимок БД; повторное обновление видит новые выполнения
и импортированные профили. Frontend не рассчитывает дефициты самостоятельно.

`POST /hr/imports` использует JSON со строковым содержимым файлов, не multipart.
`dry_run: true` проверяет без записи; false валидирует заново и сохраняет одной
транзакцией. Существующие записи не перезаписываются. Конфликтующий ID — ошибка,
идентичная запись пропускается. [Полные форматы, лимиты и ошибки](jury-import.md).
Новые профили сразу доступны движку и HR; учётные записи создаёт администратор отдельно.

### Граница текущего этапа

Авторизация, кабинет, рекомендации, симуляция, выполнение, HR-экран и HTTP-импорт реализованы.
Собранный интерфейс раздаётся FastAPI при `CQ_SERVE_FRONTEND=1`; launcher `./start.sh`
собирает его и запускает API на одном порту. Реальный AI подключён через
RealAIEngineAdapter; финальный сценарий защиты ещё требует проверки.
Сейчас API предназначен для локальной разработки и запускается на `127.0.0.1`.
Для использования токенов через интернет необходим HTTPS.
Доска планирования — отдельный сервис и к этому API не относится.

### Additional response model details

`CompletionResponse = {completion: Completion, replayed: boolean}`;
`Completion.result` is the complete `SimulationResponse` saved at completion time.
`GET .../completions` returns `{items: Completion[]}`. Date fields serialize as ISO
YYYY-MM-DD; `created_at` is an ISO datetime.

`JuryImportResult`: `dry_run`, `employees_added`, `employees_skipped`,
`history_added`, `history_skipped`, `employee_ids[]`.

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
  These can differ for career changes. Readiness measures `target`, in percent 0-100.
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

Run `python -m unittest discover -s tests -q`. Previously 48 tests passed (not rerun
during this documentation resolution), including six wrapper
integration tests, strict JSON serialization, missing-key fallback, source mapping,
empty results, null next grade, preservation of frozen ranking/score, and the full
200-profile dataset validation. Existing 42 tests remain intact.

## 3. Integration Mapping

RealAIEngineAdapter is implemented in `backend/app/real_ai_engine_adapter.py`.
The engine is frozen. FastAPI defaults to this adapter with use_llm=False, configured
by CQ_USE_LLM. Engine injection remains supported. MockEngine is an explicit emergency
preview fallback on DomainError(503) or TimeoutError; LLM failure never triggers it.

| Application / HTTP | Frozen AI / verified source | Adapter responsibility |
| --- | --- | --- |
| `recommend(context)` | `recommend(employee, history, events, catalog, as_of_date, limit=3, use_llm=False)` | Unpack context; construct RecommendationResponse with at most three items |
| `context.profile` | `employee` | Use Pydantic model_dump(mode="json"); preserve last-review snapshot |
| `history`, `events`, `catalog` | Dataset-compatible lists/dictionaries | Serialize models in JSON mode; retain skills and role_profiles |
| `as_of_date`, session dates | ISO YYYY-MM-DD | Convert dates explicitly; use configured calculation date |
| `items`, `score` | `recommendations`, `final_score` | Preserve ranking and exact scores |
| `current_skills` | Reconstructed state from existing `analyze` | Do not substitute stored assessment skills or reimplement gains |
| `progress_pct` | `readiness_before` | Ensure readiness refers to the displayed target |
| `skill_changes[]` | `skill_impacts[]` plus catalog names | Map skill_id/before/after/gain and add name; gain is the realized capped increase |
| `format`, `duration_hours`, `session_date` | Event catalog and eligible-session facts | Supply required presentation fields and preserve session identity |
| `reasons[]`, `message` | `why_this`, `why_not`, `explanation`, warnings/empty reason | Preserve verified facts and a clear empty state |
| `skills_basis`, `assessed_on` | Current reconstructed state, last_review_date | Set current basis and retain original assessment date |
| `trajectory(context)` | Existing deterministic `analyze` state/target/gaps/readiness | Build target, requirements, met_count, critical_gap_count, current_skills and progress_pct; add catalog names/types |
| `simulate(context, request)` | Frozen `digital_twin(levels, event, target, next_target, catalog)` | Validate application eligibility/session rules; map skill/readiness before-after to SimulationResponse and add context/session metadata |
| `mode: live` | Deterministic AI with optional LLM wording | Engine mode is not explanation source; deterministic AI is still live |
| `is_fallback`, `fallback_reason` | Application preview fallback versus AI explanation fallback | Keep separate: failed LLM wording must retain real AI calculations and selection |
| Completion persistence | Application storage/idempotency | Save history and simulation atomically; recalculate from fresh context |

### Backwards-compatible real-adapter response fields

RecommendationResponse additionally has `readiness_before: number | null = null`.
Each Recommendation additionally has:

```typescript
readiness_before: number | null; // default null
readiness_after: number | null;  // default null
explanation: string | null;     // default null
why_this: string | null;        // default null
why_not: string | null;         // default null
expected_career_impact: string | null; // default null
caution: string | null;         // default null
explanation_source: "llm" | "deterministic" | null; // default null
```

Existing skill_changes, score, reasons and progress fields remain. Mock and old
saved responses validate with defaults. TrajectoryResponse adds
`target_source: "explicit" | "automatic" | null = null`. Real trajectory returns
an explicit goal or the AI effective target, marked automatic when absent in the
profile; its message and UI distinguish that from an employee-selected goal.

Structured why_this/why_not, readiness before-after and skill_changes feed employee
cards. The full score_breakdown and Critic are not exposed in the HTTP employee model;
they remain available through the unchanged Python contract. AI explanation-source
fallback is distinct from is_fallback, which means replacement by the mock engine.

### Date and target semantics

- SQLite completed_at is the effective completion date when present. Jury history
  can complete after its original date. Without completed_at, dataset date remains
  a documented proxy, especially for self-paced enrollment.
- Normalize copied history for the frozen engine's date semantics; retain original
  session dates for repeatable occurrence checks. Do not overwrite stored history.
- Only completions strictly after last_review_date and no later than as_of_date
  contribute to skills. Preserve caps, higher existing skills and no-double-gain rules.
- Mock trajectory uses an explicit goal and returns no_goal otherwise; AI supports
  a default trajectory too. Align target/status/UI semantics before mapping readiness.
- Map missing requirements and invalid inputs deliberately; do not fabricate progress
  or change AI eligibility to hide errors.

HR calls recommend/trajectory per employee; keep aggregation deterministic without
per-employee LLM calls. Jury import is already implemented and must be covered by
adapter tests, including imported completion timestamps.

Acceptance: E0002/EV_005, readiness 62 to 66 at the supplied snapshot; simulation;
valid completion/repeated completion; recalculation; no candidates; review-date
boundaries; repeatable sessions; employee isolation and HR access. Scheduled events
must use a valid session/calculation date for completion, not premature completion
at the recommendation snapshot.

### Implemented adapter boundary details

- Inputs are detached `model_dump(mode="json")` copies. Non-completed dates stay intact.
- Completed self-paced rows with completed_at use that date only in the copied AI input.
  The obsolete enrollment-date warning is suppressed only for these precise records.
- Missing completed_at preserves the source date and documented approximation.
- Scheduled completed_at differing from the session date is explicitly rejected with
  HTTP 422 scheduled_completion_date_mismatch; no silent session-date substitution.
- Completed EV_036 occurrences are removed from copied upcoming_sessions before AI
  selection, so the next usable session is selected, or the activity is unavailable.
- Recommend calls the public frozen function once; the adapter never ranks candidates
  or recalculates scores. State/trajectory use build_state and readiness from the engine.
- Simulate validates application audience, prerequisites, completion and session rules,
  then calls the frozen digital_twin. Positive gains outside target gaps remain valid
  for simulation/completion, preserving application behavior after readiness reaches 100.
- HR overview uses a separate adapter with use_llm=False. Individual requests cannot
  race with a shared LLM-mode toggle.
- Launcher accepts OPENAI_API_KEY without printing it and excludes OPENAI_* from
  frontend build subprocesses. Normal requirements include the optional SDK.
