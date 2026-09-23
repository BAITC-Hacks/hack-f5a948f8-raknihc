"""SQLite persistence; connections are request-local and transactions explicit."""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .engine_port import DomainError, Engine
from .schemas import (ActivityRequest, Catalog, Completion, CompletionResponse,
                      Employee, EngineContext, Event, HistoryRecord, SimulationResponse)

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (employee_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (
    record_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    date TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_employee ON history(employee_id, date, record_id);
CREATE TABLE IF NOT EXISTS completions (
    completion_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    occurrence TEXT NOT NULL,
    idempotency_key TEXT NOT NULL, request_json TEXT NOT NULL,
    history_record_id TEXT NOT NULL UNIQUE REFERENCES history(record_id),
    payload TEXT NOT NULL,
    UNIQUE(employee_id, idempotency_key),
    UNIQUE(employee_id, event_id, occurrence)
);
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('employee', 'hr')),
    employee_id TEXT UNIQUE REFERENCES employees(employee_id),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    CHECK(role = 'hr' OR employee_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS login_attempts (
    scope TEXT PRIMARY KEY, window_start INTEGER NOT NULL, attempts INTEGER NOT NULL
);
PRAGMA user_version = 2;
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"Unsupported database schema: {version}")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        finally:
            db.close()

    def profile(self, db, employee_id):
        row = db.execute("SELECT payload FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
        if row is None:
            raise DomainError(404, "employee_not_found", "Сотрудник не найден")
        return Employee.model_validate_json(row["payload"])

    def history(self, db, employee_id):
        return [HistoryRecord.model_validate_json(r["payload"]) for r in db.execute(
            "SELECT payload FROM history WHERE employee_id=? ORDER BY date,record_id", (employee_id,))]

    def events(self, db):
        return [Event.model_validate_json(r["payload"]) for r in db.execute("SELECT payload FROM events ORDER BY event_id")]

    def catalog(self, db):
        row = db.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()
        if row is None:
            raise DomainError(503, "dataset_not_loaded", "Сначала импортируйте датасет через CLI")
        return Catalog.model_validate_json(row["value"])

    def context(self, db, employee_id, as_of_date):
        return EngineContext(profile=self.profile(db, employee_id), history=self.history(db, employee_id),
                             events=self.events(db), catalog=self.catalog(db), as_of_date=as_of_date)

    def save_completion(self, employee_id: str, request: ActivityRequest, key: str, as_of_date, engine: Engine):
        # Serialize writers to prevent two independent keys completing the same activity.
        # Engine simulation must be local/fast; LLM explanations belong to recommendations.
        with self.connect(write=True) as db:
            self.profile(db, employee_id)
            request_json = request.model_dump_json()
            previous = db.execute(
                "SELECT request_json,payload FROM completions WHERE employee_id=? AND idempotency_key=?",
                (employee_id, key),
            ).fetchone()
            if previous:
                if previous["request_json"] != request_json:
                    raise DomainError(409, "idempotency_conflict", "Ключ уже использован с другим запросом")
                return CompletionResponse(completion=Completion.model_validate_json(previous["payload"]), replayed=True)

            ctx = self.context(db, employee_id, as_of_date)
            event = next((e for e in ctx.events if e.event_id == request.event_id), None)
            if event is None:
                raise DomainError(404, "event_not_found", "Мероприятие не найдено")
            if event.format == "self_paced" and request.session_date is not None:
                raise DomainError(422, "unexpected_session", "Для self_paced не нужна дата сессии")
            if event.format != "self_paced" and request.session_date != as_of_date:
                raise DomainError(409, "completion_date_unavailable", "Сессию можно завершить только в расчётную дату её проведения")
            repeated = any(h.event_id == event.event_id and h.status == "completed" and
                           (event.event_id != "EV_036" or h.date == request.session_date) for h in ctx.history)
            if repeated:
                raise DomainError(409, "already_completed", "Мероприятие или сессия уже выполнены")

            result = SimulationResponse.model_validate(engine.simulate(ctx, request))
            if (result.employee_id, result.event_id, result.session_date, result.as_of_date, result.mode) != (
                    employee_id, request.event_id, request.session_date, as_of_date, engine.mode):
                raise DomainError(503, "invalid_engine_result", "Движок вернул результат для другого запроса")
            record_id = "H_" + uuid.uuid4().hex
            record = HistoryRecord(record_id=record_id, employee_id=employee_id, event_id=event.event_id,
                                   date=request.session_date or as_of_date, due_date=None, status="completed",
                                   completion_pct=100, score=None, feedback_rating=None, assigned_by="self",
                                   completed_at=as_of_date)
            completion = Completion(completion_id="C_" + uuid.uuid4().hex, employee_id=employee_id,
                                    event_id=event.event_id, session_date=request.session_date,
                                    completed_on=as_of_date, created_at=datetime.now(timezone.utc),
                                    history_record_id=record_id, result=result)
            db.execute("INSERT INTO history VALUES (?,?,?,?,?,?)", (record_id, employee_id, event.event_id,
                       record.date.isoformat(), record.status, record.model_dump_json()))
            occurrence = request.session_date.isoformat() if event.event_id == "EV_036" else "once"
            db.execute("INSERT INTO completions VALUES (?,?,?,?,?,?,?,?)", (
                completion.completion_id, employee_id, event.event_id, occurrence, key, request_json,
                record_id, completion.model_dump_json()))
            return CompletionResponse(completion=completion, replayed=False)
