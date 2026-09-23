# Career Quest - employee development navigator

Team Raknihc's HackAlem AI project for Halyk Bank.

## Current implementation

The repository contains the FastAPI + SQLite application layer from main and the
deterministic Career Quest AI Engine from feat/ai-engine. They are not connected yet:
FastAPI still uses MockEngine. An application-layer adapter is required.
React/frontend, HR dashboard, employee/HR authorization and HTTP jury import are not implemented.

Application layer:

- Profile, history, catalog, recommendation, simulation and completion HTTP endpoints.
- SQLite persistence with explicit transactions, idempotent completion and concurrent-request protection.
- Validated, atomic CLI import of the starter JSON/CSV dataset.
- Engine Protocol with a fresh database context for every request; clearly marked mock responses.
- Backend tests for imports, API errors, restart persistence, duplicate and concurrent completions.

AI Engine:

- Current skills reconstructed from last_review_date and completed activity gain/max_level.
- Target/next-grade gaps, critical skills, career goals, eligibility and multifactor ranking.
- Career Digital Twin: simulated skills and readiness before/after each activity.
- WHY THIS / WHY NOT explanations and Recommendation Critic.
- Optional OpenAI explanation layer with deterministic fallback; no LLM event selection or arithmetic.
- Public `from backend.app.engine import recommend`, JSON response and jury/adversarial tests.

AI Engine is frozen. Readiness measures skill coverage, not a guarantee of promotion.
Mock simulation currently leaves skills unchanged and reports unknown score/progress as null.
Recording completion works in the application, but real AI progress through HTTP is not integrated.

## Project structure

```text
backend/app/
  main.py, config.py, schemas.py     # FastAPI and HTTP models
  storage.py, import_dataset.py     # SQLite and CLI import
  engine_port.py, mock_engine.py    # application protocol and current stub
  engine/                          # deterministic engine, simulator, critic, optional LLM
backend/tests/                     # application tests
tests/                            # AI tests (root tests/ directory)
docs/                              # both contracts, algorithm and examples
data/private/                      # local dataset and SQLite; ignored by Git
requirements.txt, pyproject.toml    # backend dependencies and pytest configuration
.env.example, .gitignore
```

## Setup and run

Use Python 3.11+ with venv for the application; the main-branch instructions reported
verification on Python 3.14. Run commands from the repository root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.app.import_dataset /path/to/career_quest_dataset
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

On Debian/Ubuntu, an `ensurepip is not available` error requires the matching
python3-venv package. On Windows use `python -m venv .venv` and
`.venv/Scripts/python.exe` instead of `.venv/bin/python`.

Open http://127.0.0.1:8000/docs; health is available at `/health`.
Without import, the server starts with dataset_loaded=false, an empty employee list
and dataset_not_loaded for the catalog. This is a mock API, not a finished UI.

The teammate's host may have a user service named career-quest-api. It is not assumed
to exist on other machines. Where configured, inspect or stop it with
`systemctl --user status career-quest-api` / `systemctl --user stop career-quest-api`.
The Uvicorn command above is the reproducible server startup instruction.

## Dataset and configuration

Place employees.json, events.json, skills.json and activity_history.csv from the
starter kit in `data/private/career_quest_dataset` (or supply another directory to
CLI import). The kit has 200 profiles, 60 skills, 32 role profiles, 40 events and
2,743 history records. The snapshot date is 2026-10-01. Original data and databases
are ignored by Git; docs contain mock examples and derived AI response examples.

Default settings: snapshot 2026-10-01; see backend/app/config.py for the database path
(the current ROOT expression resolves the default beneath backend/data/private/).
To explicitly use the root data/private directory, set CQ_DB_PATH or pass --db to import.
Use the same database path for import and server. Environment settings are described
in .env.example; .env is not automatically loaded.

```bash
export CQ_DB_PATH=/absolute/path/to/career-quest.sqlite3
export CQ_AS_OF_DATE=2026-10-01
```

Importing the same files again does not overwrite data. A different dataset in an
already-populated database is rejected: use a separate --db or CQ_DB_PATH.
For a live SQLite backup, use SQLite's backup API; copying only the database file
can omit WAL changes. Additional jury-profile import into an existing database is pending.

## Application verification scenario

1. GET /api/v1/employees/E0001 and its /history.
2. GET /api/v1/employees/E0001/recommendations for mock items.
3. POST /api/v1/employees/E0001/simulations with event_id and the selected session_date
   for a scheduled event; omit session_date for self_paced.
4. POST /api/v1/employees/{id}/completions with the same body and Idempotency-Key.
   Scheduled events can only be completed on the configured calculation date.
5. Inspect /history, /completions and refreshed recommendations. The same key/body
   replays the stored result; duplicate non-repeatable completion returns 409.

Stored profile skills remain the last-review snapshot. The engine reconstructs current
skills from history; the application must not overwrite the snapshot or duplicate gain logic.

## Tests and standalone AI usage

Run both suites explicitly. Current pyproject.toml selects only backend/tests for pytest.

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -B -m unittest discover -s tests -q
.venv/bin/python -m backend.app.engine --dataset data/private/career_quest_dataset --employees E0002
```

The application tests use temporary databases and cover import validation, persistence,
idempotency, concurrent completion, club sessions, rollback, CORS and context delivery.
The AI suite passed 48 tests before this documentation resolution; its full-dataset test
skips when local data is absent. This does not establish end-to-end HTTP/AI integration.

Initial integration must use `recommend(..., use_llm=False)`. For optional explanation,
install backend/app/engine/requirements-llm.txt and supply OPENAI_API_KEY through the
process environment. Keys must never enter code, logs or Git. Deterministic operation
does not require the SDK or key.

## Integration and limitations

- [Both integration contracts and required mapping](docs/api-contract.md).
- [Scoring, Critic and explanation fallback](docs/scoring-and-explanations.md).
- [Complete Python response example](docs/integration-example.json), [HTTP mock examples](docs/examples/).
- [Dataset notes](docs/dataset-notes.md), [work plan](docs/work-plan.md).
- Real engine injection is planned through create_app(settings, engine=...). No adapter is implemented yet.
- Local-only API on 127.0.0.1; employee/HR access control is pending.
- CORS allows localhost:5173 and 127.0.0.1:5173; it does not replace authorization.
- No public employee rankings or rewards for mandatory processes.
- Full application startup including UI in one command remains pending.
