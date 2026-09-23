import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import Auth, token_digest, verify_password
from backend.app.main import create_app
from backend.app.mock_engine import MockEngine
from backend.app.storage import Store
from backend.tests.conftest import TEST_PASSWORD, sign_in

AUTH = "/api/v1/auth"
OWN = "/api/v1/employees/TEST_1"
FOREIGN = "/api/v1/employees/TEST_2"


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/employees", None),
    ("GET", OWN, None),
    ("GET", OWN + "/history", None),
    ("GET", OWN + "/recommendations", None),
    ("GET", OWN + "/trajectory", None),
    ("GET", OWN + "/completions", None),
    ("POST", OWN + "/simulations", {"event_id": "EV_SELF"}),
    ("POST", OWN + "/completions", {"event_id": "EV_SELF"}),
    ("GET", "/api/v1/events", None),
    ("GET", "/api/v1/skills", None),
    ("GET", "/api/v1/hr/summary", None),
    ("GET", AUTH + "/me", None),
    ("POST", AUTH + "/logout", None),
])
def test_no_anonymous_access(settings, method, path, body):
    with TestClient(create_app(settings)) as client:
        response = client.request(method, path, json=body, headers={"Idempotency-Key": "anonymous"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


def test_employee_cannot_read_foreign_profiles_or_hr_data(client):
    for suffix in ["", "/history", "/recommendations", "/completions", "/trajectory"]:
        assert client.get(OWN + suffix).status_code == 200
        response = client.get(FOREIGN + suffix)
        assert response.status_code == 403
        assert "TEST_2" not in response.text
    for path in ["/api/v1/employees", "/api/v1/employees?employee_id=TEST_1", "/api/v1/hr/summary"]:
        assert client.get(path).status_code == 403
    assert client.get(AUTH + "/me").json()["employee_id"] == "TEST_1"
    # The second employee also cannot access the first one.
    sign_in(client, "employee2")
    assert client.get(FOREIGN).status_code == 200
    assert client.get(OWN).status_code == 403


def test_foreign_simulation_and_completion_blocked_before_engine(settings):
    class WatchingEngine(MockEngine):
        def simulate(self, context, request):
            raise AssertionError("Unauthorised request reached engine")

    with TestClient(create_app(settings, WatchingEngine())) as client:
        sign_in(client)
        for action in ["simulations", "completions"]:
            response = client.post(FOREIGN + "/" + action, json={"event_id": "EV_SELF"},
                                   headers={"Idempotency-Key": "unauthorized"})
            assert response.status_code == 403
        with client.app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 2


def test_forged_roles_ids_and_tokens_do_not_grant_access(client):
    for headers in [{"X-Role": "hr"}, {"X-Employee-ID": "TEST_2"}, {"X-User-ID": "hr"}]:
        assert client.get(FOREIGN, headers=headers).status_code == 403
        assert client.get("/api/v1/hr/summary", headers=headers).status_code == 403
    assert client.get(FOREIGN + "?role=hr&employee_id=TEST_1").status_code == 403
    for authorization in ["Bearer " + "x" * 43, "Basic aHI6cGFzcw==", "Bearer role=hr"]:
        assert client.get("/api/v1/hr/summary", headers={"Authorization": authorization}).status_code == 401
    for extra in [{"role": "hr"}, {"employee_id": "TEST_2"}]:
        response = client.post(AUTH + "/login", json={"username": "employee1", "password": TEST_PASSWORD, **extra})
        assert response.status_code == 422
    assert client.post(AUTH + "/register", json={"role": "hr"}).status_code == 404


def test_hr_reads_all_and_summary_but_cannot_complete_for_others(client):
    sign_in(client, "hr")
    assert client.get(AUTH + "/me").json()["role"] == "hr"
    assert client.get("/api/v1/employees").json()["total"] == 2
    assert client.get("/api/v1/hr/summary").json() == {
        "employees_total": 2, "history_records_total": 2,
        "completed_history_total": 2, "app_completions_total": 0}
    for base in [OWN, FOREIGN]:
        for suffix in ["", "/history", "/recommendations", "/completions", "/trajectory"]:
            assert client.get(base + suffix).status_code == 200
        assert client.post(base + "/simulations", json={"event_id": "EV_SELF"}).status_code == 200
        response = client.post(base + "/completions", json={"event_id": "EV_SELF"},
                               headers={"Idempotency-Key": "hr-not-owner"})
        assert response.status_code == 403


def test_logout_revokes_token_and_session_survives_restart(settings):
    with TestClient(create_app(settings)) as client:
        data = sign_in(client)
        token = data["access_token"]
        assert data["token_type"] == "bearer"
        assert "password" not in data["user"]
        assert len(token) == 43
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get(OWN).status_code == 200
        assert client.post(AUTH + "/logout").status_code == 204
        assert client.get(OWN).status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get(OWN, headers={"Authorization": "Bearer " + token}).status_code == 401


def test_expired_session_rejected_and_only_hashes_stored(client):
    token = client.headers["Authorization"].removeprefix("Bearer ")
    with client.app.state.store.connect(write=True) as db:
        row = db.execute("SELECT * FROM sessions").fetchone()
        assert row["token_hash"] == token_digest(token)
        assert token not in tuple(row)
        account = db.execute("SELECT * FROM accounts WHERE username='employee1'").fetchone()
        assert TEST_PASSWORD not in tuple(account)
        assert verify_password(TEST_PASSWORD, account["password_hash"])
        db.execute("UPDATE sessions SET expires_at=0")
    assert client.get(OWN).status_code == 401


def test_password_reset_and_disabled_account_revoke_access(client):
    auth = client.app.state.auth
    first_token = client.headers["Authorization"]
    second_token = "Bearer " + sign_in(client)["access_token"]
    auth.set_password("employee1", "a-new-test-password-2026")
    for token in [first_token, second_token]:
        assert client.get(OWN, headers={"Authorization": token}).status_code == 401
    assert client.post(AUTH + "/login", json={"username": "employee1", "password": TEST_PASSWORD}).status_code == 401
    response = client.post(AUTH + "/login", json={"username": "employee1", "password": "a-new-test-password-2026"})
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    auth.disable_user("employee1")
    assert client.get(OWN).status_code == 401
    assert client.post(AUTH + "/login", json={"username": "employee1", "password": "a-new-test-password-2026"}).status_code == 401


def test_login_has_generic_errors_and_persistent_throttle(client):
    wrong = {"username": "employee1", "password": "incorrect-password"}
    missing = {"username": "absent", "password": "incorrect-password"}
    existing_error = client.post(AUTH + "/login", json=wrong)
    assert existing_error.status_code == 401
    assert client.post(AUTH + "/login", json=missing).json() == existing_error.json()
    for _ in range(9):
        assert client.post(AUTH + "/login", json=wrong).status_code == 401
    response = client.post(AUTH + "/login", json=wrong)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "300"
    with client.app.state.store.connect(write=True) as db:
        db.execute("UPDATE login_attempts SET window_start=0")
    assert client.post(AUTH + "/login", json={"username": "employee1", "password": TEST_PASSWORD}).status_code == 200


def test_account_binding_and_role_are_validated(settings):
    auth = Auth(Store(settings.db_path), settings.session_ttl_seconds)
    for username, role, employee_id in [("bad", "admin", None), ("no-profile", "employee", None),
                                       ("duplicate", "employee", "TEST_1"), ("hr", "hr", None)]:
        with pytest.raises(ValueError):
            auth.create_user(username, TEST_PASSWORD, role, employee_id)
    with pytest.raises(ValueError):
        auth.create_user("weak-password", "123", "hr")


def test_roles_are_read_from_database_on_each_request(client):
    with client.app.state.store.connect(write=True) as db:
        db.execute("UPDATE accounts SET is_active=0 WHERE username='employee1'")
    assert client.get(OWN).status_code == 401


def test_v1_migration_preserves_existing_data(client, settings):
    response = client.post(OWN + "/completions", json={"event_id": "EV_SELF"}, headers={"Idempotency-Key": "migration"})
    assert response.status_code == 201
    with sqlite3.connect(settings.db_path) as db:
        db.executescript("DROP TABLE sessions; DROP TABLE accounts; DROP TABLE login_attempts; PRAGMA user_version=1;")
    store = Store(settings.db_path)
    store.initialize()
    store.initialize()
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_swagger_marks_all_data_routes_as_protected(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path, methods in paths.items():
        if path in ["/health", AUTH + "/login"]:
            continue
        for operation in methods.values():
            assert operation["security"] == [{"HTTPBearer": []}], path
