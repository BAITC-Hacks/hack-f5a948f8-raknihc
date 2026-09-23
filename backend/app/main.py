from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, ROOT
from .auth import (Auth, Credentials, CurrentUser, require_hr, require_own_profile,
                   require_profile_access, require_user)
from .engine_port import DomainError, Engine
from .mock_engine import MockEngine
from .schemas import (ActivityRequest, Catalog, Completion, CompletionList, CompletionResponse,
                      Employee, EmployeePage, EventList, Health, HistoryList,
                      RecommendationResponse, SimulationResponse)
from .schemas import HRSummary, LoginRequest, LoginResponse, User, TrajectoryResponse
from .storage import Store
from .hr import overview
from .jury_import import import_profiles, ImportProblem
from .schemas import HROverview, JuryImportRequest, JuryImportResult


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine if engine is not None else MockEngine()
    store = Store(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="Career Quest API", version="0.2.0", lifespan=lifespan,
                  description="Вход: /api/v1/auth/login. Скопируйте access_token в Authorize. Движок пока mock.")
    app.state.store, app.state.engine, app.state.settings = store, engine, settings
    auth = app.state.auth = Auth(store, settings.session_ttl_seconds)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key", "Authorization"])
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        if exc.status == 429:
            headers["Retry-After"] = "300"
        detail = {"code": exc.code, "message": exc.message}
        if isinstance(exc, ImportProblem):
            detail['issues'] = exc.issues
        return JSONResponse(status_code=exc.status, headers=headers, content={"detail": detail})

    @app.post("/api/v1/auth/login", response_model=LoginResponse, tags=["auth"])
    def login(body: LoginRequest):
        return auth.login(body.username, body.password)

    @api.get("/auth/me", response_model=User, tags=["auth"])
    def me(user: CurrentUser):
        return user

    @api.post("/auth/logout", status_code=204, tags=["auth"])
    def logout(credentials: Credentials):
        auth.logout(credentials.credentials)
        return Response(status_code=204)

    @app.get("/health", response_model=Health, tags=["system"])
    def health():
        with store.connect() as db:
            loaded = db.execute("SELECT 1 FROM metadata WHERE key='dataset_digest'").fetchone() is not None
        return Health(status="ok", engine_mode=engine.mode, as_of_date=settings.as_of_date, dataset_loaded=loaded)

    @api.get("/employees", response_model=EmployeePage, tags=["employees"], dependencies=[Depends(require_hr)])
    def employees(offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50):
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
            rows = db.execute("SELECT payload FROM employees ORDER BY employee_id LIMIT ? OFFSET ?", (limit, offset))
            return EmployeePage(items=[Employee.model_validate_json(r["payload"]) for r in rows],
                                total=total, offset=offset, limit=limit)

    @api.get("/employees/{employee_id}", response_model=Employee, tags=["employees"], dependencies=[Depends(require_profile_access)])
    def profile(employee_id: str):
        with store.connect() as db:
            return store.profile(db, employee_id)

    @api.get("/employees/{employee_id}/history", response_model=HistoryList, tags=["employees"], dependencies=[Depends(require_profile_access)])
    def history(employee_id: str):
        with store.connect() as db:
            store.profile(db, employee_id)
            return HistoryList(items=store.history(db, employee_id))

    @api.get("/events", response_model=EventList, tags=["catalog"])
    def events():
        with store.connect() as db:
            return EventList(items=store.events(db))

    @api.get("/skills", response_model=Catalog, tags=["catalog"])
    def skills():
        with store.connect() as db:
            return store.catalog(db)

    def context(employee_id):
        with store.connect() as db:
            return store.context(db, employee_id, settings.as_of_date)

    def preview_with_fallback(operation, ctx, *args):
        try:
            return getattr(engine, operation)(ctx, *args)
        except (DomainError, TimeoutError) as exc:
            if isinstance(exc, DomainError) and exc.status != 503:
                raise
            result = getattr(MockEngine(), operation)(ctx, *args)
            return result.model_copy(update={
                "is_fallback": True,
                "fallback_reason": "Основной сервис временно недоступен. Показан предварительный расчёт по каталогу с учётом завершённого обучения.",
            })

    @api.get("/employees/{employee_id}/recommendations", response_model=RecommendationResponse, tags=["engine"], dependencies=[Depends(require_profile_access)])
    def recommendations(employee_id: str):
        return preview_with_fallback("recommend", context(employee_id))

    @api.get("/employees/{employee_id}/trajectory", response_model=TrajectoryResponse, tags=["engine"], dependencies=[Depends(require_profile_access)])
    def trajectory(employee_id: str):
        return engine.trajectory(context(employee_id))

    @api.post("/employees/{employee_id}/simulations", response_model=SimulationResponse, tags=["engine"], dependencies=[Depends(require_profile_access)])
    def simulate(employee_id: str, body: ActivityRequest):
        return preview_with_fallback("simulate", context(employee_id), body)

    @api.post("/employees/{employee_id}/completions", response_model=CompletionResponse,
              status_code=201, responses={200: {"model": CompletionResponse, "description": "Idempotent replay"}}, tags=["completions"],
              dependencies=[Depends(require_own_profile)])
    def complete(employee_id: str, body: ActivityRequest, response: Response,
                 idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]):
        if not idempotency_key.strip():
            raise DomainError(422, "invalid_idempotency_key", "Ключ не может состоять из пробелов")
        result = store.save_completion(employee_id, body, idempotency_key, settings.as_of_date, engine)
        response.status_code = 200 if result.replayed else 201
        return result

    @api.get("/employees/{employee_id}/completions", response_model=CompletionList, tags=["completions"], dependencies=[Depends(require_profile_access)])
    def completions(employee_id: str):
        with store.connect() as db:
            store.profile(db, employee_id)
            rows = db.execute("SELECT payload FROM completions WHERE employee_id=? ORDER BY rowid", (employee_id,))
            return CompletionList(items=[Completion.model_validate_json(r["payload"]) for r in rows])

    @api.get("/hr/summary", response_model=HRSummary, tags=["hr"], dependencies=[Depends(require_hr)])
    def hr_summary():
        with store.connect() as db:
            return HRSummary(
                employees_total=db.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
                history_records_total=db.execute("SELECT COUNT(*) FROM history").fetchone()[0],
                completed_history_total=db.execute("SELECT COUNT(*) FROM history WHERE status='completed'").fetchone()[0],
                app_completions_total=db.execute("SELECT COUNT(*) FROM completions").fetchone()[0],
            )

    @api.get('/hr/overview', response_model=HROverview, tags=['hr'], dependencies=[Depends(require_hr)])
    def hr_overview():
        return overview(store, engine, settings.as_of_date)

    @api.post('/hr/imports', response_model=JuryImportResult, tags=['hr'], dependencies=[Depends(require_hr)])
    def jury_import(body: JuryImportRequest):
        return import_profiles(store, body, settings.as_of_date)

    app.include_router(api)
    if settings.serve_frontend:
        app.mount('/', StaticFiles(directory=ROOT / 'frontend/dist', html=True), name='frontend')
    return app


app = create_app()
