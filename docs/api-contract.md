# Контракт API и движка v1

Статус: первая реализация для `feat/app-ui`; контракт предложен для интеграции
с участником AI engine. Источник точных типов — `backend/app/schemas.py`,
машиночитаемая схема HTTP — `/openapi.json`. Префикс API — `/api/v1`.

## Данные и хранение

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

## HTTP

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

## Интерфейс движка

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

## Поведение mock

`mode: mock` виден во всех ответах движка и сохранённых результатах.
Простая заглушка выбирает до трёх событий в порядке каталога с базовой проверкой
роли, грейда, prerequisites, завершений и расписания. Это не ранжирование.
Навыки возвращаются из профиля без восстановления истории; симуляция сохраняет
их неизменными. Проценты и score равны null. Сохранение выполнения действительно
меняет историю и исключает завершённое событие из последующих mock-рекомендаций.
Никакой LLM или числовой модели развития пока нет.

## Граница текущего этапа

Авторизация сотрудник/HR, UI и HTTP-импорт — следующие задачи. Сейчас API
предназначен для локальной разработки и запускается на `127.0.0.1`.
Открывать этот backend публично до реализации разграничения доступа нельзя.
Доска планирования — отдельный сервис и к этому API не относится.
