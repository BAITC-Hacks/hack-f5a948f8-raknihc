from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app.engine_port import DomainError
from backend.app.main import create_app
from backend.app.mock_engine import MockEngine
from backend.tests.conftest import sign_in

BASE = "/api/v1/employees/TEST_1"


def complete(client, event="EV_SELF", key="first", session=None):
    body = {"event_id": event}
    if session:
        body["session_date"] = session
    return client.post(BASE + "/completions", json=body, headers={"Idempotency-Key": key})


def test_catalog_profiles_and_openapi(client):
    assert client.get("/health").json() == {
        "status": "ok", "engine_mode": "mock", "as_of_date": "2026-10-01", "dataset_loaded": True}
    sign_in(client, "hr")
    page = client.get("/api/v1/employees?offset=1&limit=1").json()
    assert page["total"] == 2
    assert [p["employee_id"] for p in page["items"]] == ["TEST_2"]
    assert client.get("/api/v1/employees?limit=201").status_code == 422
    assert client.get(BASE).json()["skills"] == {"SK_TEST": 1}
    history = client.get(BASE + "/history").json()["items"]
    assert len(history) == 2  # Preserve repeated mandatory training in source data.
    assert history[0]["score"] is None
    assert len(client.get("/api/v1/events").json()["items"]) == 5
    assert len(client.get("/api/v1/skills").json()["role_profiles"]) == 2
    spec = client.get("/openapi.json").json()
    assert "/api/v1/employees/{employee_id}/completions" in spec["paths"]
    assert client.get("/docs").status_code == 200


def test_mock_simulation_does_not_mutate_and_marks_unknown_progress(client):
    before = client.get(BASE).json()
    history = client.get(BASE + "/history").json()
    response = client.post(BASE + "/simulations", json={"event_id": "EV_SELF"})
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "mock"
    assert result["progress_after_pct"] is None
    assert result["skills_before"] == before["skills"]
    assert result["skills_after"] == {"SK_TEST": 2}
    assert result["skill_changes"] == [{"skill_id": "SK_TEST", "name": "Test Skill", "before": 1, "after": 2, "gain": 1}]
    assert client.get(BASE).json() == before
    assert client.get(BASE + "/history").json() == history


def test_completion_replay_conflicts_and_restart(client, settings):
    before = client.get(BASE).json()
    first = complete(client)
    assert first.status_code == 201
    assert first.json()["replayed"] is False
    saved = first.json()["completion"]
    assert saved["result"]["mode"] == "mock"
    assert len(client.get(BASE + "/history").json()["items"]) == 3
    assert client.get(BASE).json() == before  # Do not double-count history by overwriting assessments.
    items = client.get(BASE + "/recommendations").json()["items"]
    assert "EV_SELF" not in [x["event_id"] for x in items]
    assert complete(client).status_code == 200
    assert complete(client).json() == {"completion": saved, "replayed": True}
    assert complete(client, key="different").status_code == 409
    assert complete(client, event="EV_NEXT").json()["detail"]["code"] == "idempotency_conflict"
    with TestClient(create_app(settings)) as restarted:
        sign_in(restarted)
        assert complete(restarted).json()["completion"] == saved
        assert len(restarted.get(BASE + "/completions").json()["items"]) == 1
        assert len(restarted.get(BASE + "/history").json()["items"]) == 3


def test_scheduled_simulation_completion_and_repeatable_club(client, settings):
    body = {"event_id": "EV_SESSION", "session_date": "2026-10-02"}
    assert client.post(BASE + "/simulations", json=body).status_code == 200
    assert complete(client, "EV_SESSION", session="2026-10-02").status_code == 409
    assert complete(client, "EV_036", "club1", "2026-10-01").status_code == 201
    assert complete(client, "EV_036", "club2", "2026-10-01").status_code == 409
    future = replace(settings, as_of_date=date(2026, 10, 8))
    with TestClient(create_app(future)) as later:
        sign_in(later)
        assert complete(later, "EV_036", "club2", "2026-10-08").status_code == 201
        assert len(later.get(BASE + "/completions").json()["items"]) == 2


@pytest.mark.parametrize("body,status", [
    ({"event_id": "missing"}, 404),
    ({"event_id": "EV_MAND"}, 409),
    ({"event_id": "EV_SELF", "skills": {}}, 422),
    ({"event_id": "EV_SELF", "session_date": "2026-10-01"}, 422),
    ({"event_id": "EV_SESSION"}, 409),
])
def test_invalid_actions_leave_history_unchanged(client, body, status):
    response = client.post(BASE + "/completions", json=body, headers={"Idempotency-Key": "invalid"})
    assert response.status_code == status
    assert len(client.get(BASE + "/history").json()["items"]) == 2
    assert client.get(BASE + "/completions").json()["items"] == []


def test_missing_profile_key_and_unknown_fields(client):
    for suffix in ["", "/history", "/recommendations", "/completions"]:
        assert client.get("/api/v1/employees/absent" + suffix).status_code == 403
    assert client.post(BASE + "/completions", json={"event_id": "EV_SELF"}).status_code == 422
    assert complete(client, key=" ").status_code == 422
    sign_in(client, "hr")
    assert client.get("/api/v1/employees/absent").status_code == 404


def test_engine_receives_current_database_on_every_request(settings):
    class SpyEngine(MockEngine):
        def __init__(self):
            self.contexts = []

        def recommend(self, context):
            self.contexts.append(context)
            return super().recommend(context)

    engine = SpyEngine()
    with TestClient(create_app(settings, engine)) as client:
        sign_in(client)
        client.get(BASE + "/recommendations")
        assert complete(client).status_code == 201
        client.get(BASE + "/recommendations")
    assert [len(c.history) for c in engine.contexts] == [2, 3]
    assert engine.contexts[-1].profile.employee_id == "TEST_1"
    assert len(engine.contexts[-1].events) == 5
    assert engine.contexts[-1].catalog.skills[0].skill_id == "SK_TEST"
    assert engine.contexts[-1].as_of_date == date(2026, 10, 1)


def test_engine_failure_rolls_back(settings):
    class UnavailableEngine(MockEngine):
        def simulate(self, context, request):
            raise DomainError(503, "engine_unavailable", "Try again")

    with TestClient(create_app(settings, UnavailableEngine())) as client:
        sign_in(client)
        assert complete(client).status_code == 503
        assert client.get(BASE + "/completions").json()["items"] == []
        assert len(client.get(BASE + "/history").json()["items"]) == 2


@pytest.mark.parametrize("keys,expected", [(["same", "same"], [200, 201]), (["a", "b"], [201, 409])])
def test_concurrent_completions_only_save_once(client, keys, expected):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda key: complete(client, key=key), keys))
    assert sorted(r.status_code for r in responses) == expected
    assert len(client.get(BASE + "/completions").json()["items"]) == 1
    assert len(client.get(BASE + "/history").json()["items"]) == 3


def test_cors_allows_local_frontend_only(client):
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "content-type,idempotency-key"}
    response = client.options(BASE + "/completions", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    headers["Origin"] = "https://unknown.example"
    assert client.options(BASE + "/completions", headers=headers).status_code == 400
