from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .engine_port import DomainError, Engine
from .mock_engine import MockEngine
from .schemas import (ActivityRequest, Catalog, Completion, CompletionList, CompletionResponse,
                      Employee, EmployeePage, EventList, Health, HistoryList,
                      RecommendationResponse, SimulationResponse)
from .storage import Store


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine if engine is not None else MockEngine()
    store = Store(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="Career Quest API", version="0.1.0", lifespan=lifespan,
                  description="Локальный backend. Движок mock; авторизация сотрудник/HR ещё не реализована.")
    app.state.store, app.state.engine, app.state.settings = store, engine, settings
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])

    @app.exception_handler(DomainError)
    async def domain_error_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.get("/health", response_model=Health, tags=["system"])
    def health():
        with store.connect() as db:
            loaded = db.execute("SELECT 1 FROM metadata WHERE key='dataset_digest'").fetchone() is not None
        return Health(status="ok", engine_mode=engine.mode, as_of_date=settings.as_of_date, dataset_loaded=loaded)

    @app.get("/api/v1/employees", response_model=EmployeePage, tags=["employees"])
    def employees(offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50):
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
            rows = db.execute("SELECT payload FROM employees ORDER BY employee_id LIMIT ? OFFSET ?", (limit, offset))
            return EmployeePage(items=[Employee.model_validate_json(r["payload"]) for r in rows],
                                total=total, offset=offset, limit=limit)

    @app.get("/api/v1/employees/{employee_id}", response_model=Employee, tags=["employees"])
    def profile(employee_id: str):
        with store.connect() as db:
            return store.profile(db, employee_id)

    @app.get("/api/v1/employees/{employee_id}/history", response_model=HistoryList, tags=["employees"])
    def history(employee_id: str):
        with store.connect() as db:
            store.profile(db, employee_id)
            return HistoryList(items=store.history(db, employee_id))

    @app.get("/api/v1/events", response_model=EventList, tags=["catalog"])
    def events():
        with store.connect() as db:
            return EventList(items=store.events(db))

    @app.get("/api/v1/skills", response_model=Catalog, tags=["catalog"])
    def skills():
        with store.connect() as db:
            return store.catalog(db)

    def context(employee_id):
        with store.connect() as db:
            return store.context(db, employee_id, settings.as_of_date)

    @app.get("/api/v1/employees/{employee_id}/recommendations", response_model=RecommendationResponse, tags=["engine"])
    def recommendations(employee_id: str):
        return engine.recommend(context(employee_id))

    @app.post("/api/v1/employees/{employee_id}/simulations", response_model=SimulationResponse, tags=["engine"])
    def simulate(employee_id: str, body: ActivityRequest):
        return engine.simulate(context(employee_id), body)

    @app.post("/api/v1/employees/{employee_id}/completions", response_model=CompletionResponse,
              status_code=201, responses={200: {"model": CompletionResponse, "description": "Idempotent replay"}}, tags=["completions"])
    def complete(employee_id: str, body: ActivityRequest, response: Response,
                 idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]):
        if not idempotency_key.strip():
            raise DomainError(422, "invalid_idempotency_key", "Ключ не может состоять из пробелов")
        result = store.save_completion(employee_id, body, idempotency_key, settings.as_of_date, engine)
        response.status_code = 200 if result.replayed else 201
        return result

    @app.get("/api/v1/employees/{employee_id}/completions", response_model=CompletionList, tags=["completions"])
    def completions(employee_id: str):
        with store.connect() as db:
            store.profile(db, employee_id)
            rows = db.execute("SELECT payload FROM completions WHERE employee_id=? ORDER BY rowid", (employee_id,))
            return CompletionList(items=[Completion.model_validate_json(r["payload"]) for r in rows])

    return app


app = create_app()
