import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.import_dataset import import_dataset
from backend.app.main import create_app
from backend.tests.conftest import TEST_PASSWORD, sign_in


def test_reimport_preserves_completions(client, settings, dataset_dir):
    route = "/api/v1/employees/TEST_1"
    assert client.post(route + "/completions", json={"event_id": "EV_SELF"},
                       headers={"Idempotency-Key": "seed-check"}).status_code == 201
    assert import_dataset(dataset_dir, settings.db_path)["imported"] is False
    assert len(client.get(route + "/history").json()["items"]) == 3
    filename = dataset_dir / "employees.json"
    payload = json.loads(filename.read_text())
    payload["employees"][0]["full_name"] = "Changed"
    filename.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="different dataset"):
        import_dataset(dataset_dir, settings.db_path)
    assert client.get(route).json()["full_name"] == "Test Employee"


@pytest.mark.parametrize("corruption", ["reference", "duplicate", "level"])
def test_invalid_dataset_does_not_write(tmp_path, dataset_dir, corruption):
    filename = dataset_dir / "employees.json"
    payload = json.loads(filename.read_text())
    if corruption == "reference":
        payload["employees"][0]["manager_id"] = "ABSENT"
    elif corruption == "duplicate":
        payload["employees"].append(payload["employees"][0])
    else:
        payload["employees"][0]["skills"]["SK_TEST"] = 9
    filename.write_text(json.dumps(payload))
    path = tmp_path / "invalid.sqlite3"
    with pytest.raises(ValueError):
        import_dataset(dataset_dir, path)
    assert not path.exists()


def test_empty_database_starts_with_import_instruction(tmp_path):
    with TestClient(create_app(Settings(db_path=tmp_path / "empty.sqlite3"))) as client:
        assert client.get("/health").json()["dataset_loaded"] is False
        client.app.state.auth.create_user("hr", TEST_PASSWORD, "hr")
        sign_in(client, "hr")
        assert client.get("/api/v1/employees").json()["total"] == 0
        assert client.get("/api/v1/skills").json()["detail"]["code"] == "dataset_not_loaded"
