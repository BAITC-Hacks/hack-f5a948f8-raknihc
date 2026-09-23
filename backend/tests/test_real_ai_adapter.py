"""Real AI integration: no network calls, original dataset remains read-only."""
from datetime import date
from pathlib import Path
from unittest.mock import patch
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.engine import load_dataset
from backend.app.engine_port import DomainError
from backend.app.main import create_app
from backend.app.real_ai_engine_adapter import RealAIEngineAdapter
from backend.app.schemas import EngineContext, HistoryRecord, ActivityRequest
from backend.app.storage import Store
from backend.tests.conftest import sign_in
from scripts.start import load_env

BASE = "/api/v1/employees/TEST_1"


@pytest.fixture
def context(settings):
    with Store(settings.db_path).connect() as db:
        return Store(settings.db_path).context(db, "TEST_1", settings.as_of_date)


def row(context, event="EV_SELF", day="2026-08-01", completed_at=None, status="completed"):
    return HistoryRecord(record_id="NEW_ROW", employee_id=context.profile.employee_id,
        event_id=event, date=day, completed_at=completed_at, due_date=None, status=status,
        completion_pct=100 if status == "completed" else 0, score=None,
        feedback_rating=None, assigned_by="self")


def test_e0002_real_dataset():
    directory = Path(__file__).resolve().parents[2] / "data/private/career_quest_dataset"
    if not (directory / "employees.json").exists():
        pytest.skip("Local Career Quest dataset required")
    data = load_dataset(directory)
    ctx = EngineContext(profile=next(p for p in data["employees"] if p["employee_id"] == "E0002"),
        history=[{k: v if v != "" else None for k, v in row.items()} for row in data["history"]], events=data["events"], as_of_date=data["as_of_date"],
        catalog={key: data["catalog"][key] for key in ("skills", "role_profiles", "proficiency_scale")})
    before = ctx.model_dump(mode="json")
    adapter = RealAIEngineAdapter()
    response = adapter.recommend(ctx)
    top = response.items[0]
    assert top.event_id == "EV_005"
    assert top.score == pytest.approx(5.408333, abs=0.000001)
    assert (top.readiness_before, top.readiness_after) == (62, 66)
    assert top.why_this and top.why_not and top.explanation and top.skill_changes
    assert top.explanation_source == "deterministic"
    simulation = adapter.simulate(ctx, ActivityRequest(event_id=top.event_id, session_date=top.session_date))
    assert (simulation.progress_before_pct, simulation.progress_after_pct) == (62, 66)
    assert ctx.model_dump(mode="json") == before
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


@pytest.mark.parametrize("day,completed_at,expected", [
    ("2026-08-01", None, 1),
    ("2026-08-01", "2026-09-15", 2),
    ("2026-09-15", None, 2),
    ("2026-08-01", "2026-10-02", 1),
    ("2026-08-01", "2026-09-01", 1),
])
def test_self_paced_completion_dates(context, day, completed_at, expected):
    context.history.append(row(context, day=day, completed_at=completed_at))
    original = context.model_dump(mode="json")
    result = RealAIEngineAdapter().trajectory(context)
    assert result.current_skills["SK_TEST"] == expected
    assert result.requirements[0].current_level == expected
    assert result.assessed_on == context.profile.last_review_date
    assert result.skills_basis == "current"
    assert context.model_dump(mode="json") == original
    if completed_at is None:
        assert "enrollment date used" in result.message
    else:
        assert "Completion date unavailable" not in result.message


def test_noncompleted_date_preserved(context):
    context.history.append(row(context, status="in_progress"))
    converted = RealAIEngineAdapter._inputs(context)
    assert converted["history"][-1]["date"] == "2026-08-01"
    assert RealAIEngineAdapter().trajectory(context).current_skills["SK_TEST"] == 1


@pytest.mark.parametrize("explicit", [True, False])
def test_target_source(context, explicit):
    if not explicit:
        context.profile.career_goal = None
    result = RealAIEngineAdapter().trajectory(context)
    assert result.target.target_grade == "Middle"
    assert result.target_source == ("explicit" if explicit else "automatic")
    assert result.progress_pct == 50
    if not explicit:
        assert "not selected by the employee" in result.message


def test_scheduled_dates_preserved_or_explicitly_rejected(context):
    context.history.append(row(context, event="EV_SESSION", day="2026-09-15", completed_at="2026-09-15"))
    converted = RealAIEngineAdapter._inputs(context)
    assert converted["history"][-1]["date"] == "2026-09-15"
    assert RealAIEngineAdapter().trajectory(context).current_skills["SK_TEST"] == 2
    context.history[-1].completed_at = date(2026, 9, 16)
    before = context.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        RealAIEngineAdapter().trajectory(context)
    assert error.value.code == "scheduled_completion_date_mismatch"
    assert context.model_dump(mode="json") == before


@pytest.mark.parametrize("future", [True, False])
def test_completed_club_session_never_exposed(context, future):
    # A completion on the review date excludes the occurrence without applying a gain.
    context.profile.last_review_date = context.as_of_date
    context.history.append(row(context, event="EV_036", day="2026-10-01", completed_at="2026-10-01"))
    club = next(event for event in context.events if event.event_id == "EV_036")
    if not future:
        club.upcoming_sessions = [context.as_of_date]
    original = context.model_dump(mode="json")
    adapter = RealAIEngineAdapter()
    result = adapter.recommend(context)
    items = [item for item in result.items if item.event_id == "EV_036"]
    if future:
        assert items and items[0].session_date == date(2026, 10, 8)
    else:
        assert items == []
    with pytest.raises(DomainError) as error:
        adapter.simulate(context, ActivityRequest(event_id="EV_036", session_date=context.as_of_date))
    assert error.value.code == "session_unavailable"
    assert context.model_dump(mode="json") == original


@pytest.mark.parametrize("event,session,code", [
    ("EV_SELF", "2026-10-01", "unexpected_session"),
    ("EV_SESSION", "2026-09-01", "session_unavailable"),
    ("EV_SESSION", None, "session_unavailable"),
    ("MISSING", None, "event_not_found"),
])
def test_invalid_simulation_sessions(context, event, session, code):
    with pytest.raises(DomainError) as error:
        RealAIEngineAdapter().simulate(context, ActivityRequest(event_id=event, session_date=session))
    assert error.value.code == code


def test_completion_replay_recalculation_and_readonly_simulation(settings):
    app = create_app(settings)
    assert isinstance(app.state.engine, RealAIEngineAdapter)
    with TestClient(app) as client:
        sign_in(client)
        profile = client.get(BASE).json()
        history = client.get(BASE + "/history").json()
        with Store(settings.db_path).connect() as db:
            before = list(db.iterdump())
        response = client.post(BASE + "/simulations", json={"event_id": "EV_SELF"})
        assert response.status_code == 200
        assert response.json()["progress_after_pct"] == 100
        with Store(settings.db_path).connect() as db:
            assert list(db.iterdump()) == before
        assert client.get(BASE + "/history").json() == history
        body = {"event_id": "EV_SELF"}
        headers = {"Idempotency-Key": "real-completion"}
        first = client.post(BASE + "/completions", json=body, headers=headers)
        assert first.status_code == 201, first.text
        replay = client.post(BASE + "/completions", json=body, headers=headers)
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert replay.json()["completion"] == first.json()["completion"]
        assert len(client.get(BASE + "/history").json()["items"]) == len(history["items"]) + 1
        assert client.get(BASE).json() == profile
        result = client.get(BASE + "/recommendations").json()
        assert result["mode"] == "live" and not result["is_fallback"]
        assert result["current_skills"]["SK_TEST"] == 2
        assert result["progress_pct"] == 100
        assert result["items"] == [] and result["message"]
        assert client.get(BASE + "/trajectory").json()["progress_pct"] == 100
        duplicate = client.post(BASE + "/completions", json=body, headers={"Idempotency-Key": "another"})
        assert duplicate.status_code == 409


@pytest.mark.parametrize("failure", ["missing", "api_error"])
def test_llm_failure_keeps_real_selection(context, monkeypatch, failure):
    baseline = RealAIEngineAdapter().recommend(context)
    if failure == "missing":
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-test-credential")
    with patch("openai.OpenAI", side_effect=TimeoutError("test timeout")) as call:
        result = RealAIEngineAdapter(use_llm=True).recommend(context)
    assert call.call_count == (1 if failure == "api_error" else 0)
    assert result.model_dump() == baseline.model_dump()
    assert result.mode == "live" and not result.is_fallback


def test_real_auth_hr_and_bulk_disables_llm(settings, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-test-credential")
    app = create_app(settings, engine=RealAIEngineAdapter(use_llm=True))
    with TestClient(app) as client, patch("openai.OpenAI", side_effect=AssertionError("No HR LLM calls")) as sdk:
        assert client.get(BASE + "/recommendations").status_code == 401
        sign_in(client)
        assert client.get('/api/v1/employees/TEST_2/recommendations').status_code == 403
        assert client.get('/api/v1/hr/overview').status_code == 403
        sign_in(client, "hr")
        assert client.get('/api/v1/employees/TEST_2/trajectory').status_code == 200
        response = client.get('/api/v1/hr/overview')
        assert response.status_code == 200, response.text
        assert response.json()["mode"] == "live"
        assert len(response.json()["employees"]) == 2
        sdk.assert_not_called()


def test_launcher_accepts_optional_key_without_output(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "local-config"
    path.write_text("OPENAI_API_KEY=not-a-real-test-credential\nCQ_USE_LLM=1\n")
    load_env(path)
    from backend.app.config import Settings
    assert Settings.from_env().use_llm
    assert capsys.readouterr().out == ""
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("CQ_USE_LLM")


@pytest.mark.parametrize("case", ["prerequisite", "audience", "mandatory", "completed", "no_gain"])
def test_simulation_eligibility(context, case):
    event = next(event for event in context.events if event.event_id == "EV_SELF")
    if case == "prerequisite":
        event.prerequisites = {"SK_TEST": 5}
    elif case == "audience":
        event.target_roles = []
    elif case == "mandatory":
        event.mandatory = True
    elif case == "completed":
        context.history.append(row(context))
    else:
        context.profile.skills["SK_TEST"] = 5
    with pytest.raises(DomainError) as error:
        RealAIEngineAdapter().simulate(context, ActivityRequest(event_id="EV_SELF"))
    assert error.value.status == 409


def test_simulate_non_target_gain_after_target_met(context):
    context.profile.skills["SK_TEST"] = 2
    adapter = RealAIEngineAdapter()
    assert adapter.recommend(context).items == []
    result = adapter.simulate(context, ActivityRequest(event_id="EV_SELF"))
    assert result.skills_after["SK_TEST"] == 3
    assert result.progress_before_pct == result.progress_after_pct == 100


def test_full_dataset_through_application_models():
    from backend.app.import_dataset import load_dataset as load_application_dataset
    directory = Path(__file__).resolve().parents[2] / "data/private/career_quest_dataset"
    if not (directory / "employees.json").exists():
        pytest.skip("Local Career Quest dataset required")
    employees, events, catalog, history, _, as_of = load_application_dataset(directory)
    adapter = RealAIEngineAdapter()
    assert len(employees) == 200
    for employee in employees:
        ctx = EngineContext(profile=employee, history=[h for h in history if h.employee_id == employee.employee_id],
                            events=events, catalog=catalog, as_of_date=as_of)
        result = adapter.recommend(ctx)
        trajectory = adapter.trajectory(ctx)
        assert result.progress_pct == trajectory.progress_pct
        assert result.current_skills == trajectory.current_skills
        assert len(result.items) <= 3
        json.dumps(result.model_dump(mode="json"), allow_nan=False)
        for item in result.items:
            preview = adapter.simulate(ctx, ActivityRequest(event_id=item.event_id, session_date=item.session_date))
            assert preview.progress_after_pct == item.readiness_after
            assert preview.skill_changes == item.skill_changes


def test_real_jury_import_and_recommendations(settings):
    with TestClient(create_app(settings)) as client:
        sign_in(client, "hr")
        profile = client.get(BASE).json()
        profile["employee_id"] = "JURY_REAL"
        profile["career_goal"] = None
        response = client.post('/api/v1/hr/imports', json={"employees_json": json.dumps([profile]), "dry_run": False})
        assert response.status_code == 200, response.text
        assert response.json()["employees_added"] == 1
        imported = client.get('/api/v1/employees/JURY_REAL/recommendations')
        assert imported.status_code == 200 and imported.json()["items"]
        assert imported.json()["mode"] == "live"
        assert client.get('/api/v1/employees/JURY_REAL/trajectory').json()["target_source"] == "automatic"
        assert client.get('/api/v1/employees').json()["total"] == 3
