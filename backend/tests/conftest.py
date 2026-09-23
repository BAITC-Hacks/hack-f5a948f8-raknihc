import csv
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.import_dataset import import_dataset
from backend.app.main import create_app


@pytest.fixture
def dataset_dir(tmp_path):
    directory = tmp_path / "dataset"
    directory.mkdir()
    meta = {"dataset": "test", "version": "1.0", "as_of_date": "2026-10-01"}
    profile = {
        "employee_id": "TEST_1", "full_name": "Test Employee", "department": "Test", "role": "Engineer",
        "grade": "Junior", "manager_id": None, "hire_date": "2025-01-01", "tenure_months": 21,
        "work_format": "remote", "preferred_language": "ru", "career_goal": {"target_role": "Engineer", "target_grade": "Middle"},
        "skills": {"SK_TEST": 1}, "last_review_date": "2026-09-01",
    }
    event = {
        "event_id": "EV_SELF", "title": "Test Course", "description": "Fixture", "type": "course",
        "format": "self_paced", "duration_hours": 2, "mandatory": False,
        "target_roles": ["Engineer"], "target_grades": ["Junior"],
        "develops_skills": [{"skill_id": "SK_TEST", "gain": 1, "max_level": 3}],
        "prerequisites": {}, "upcoming_sessions": [],
    }
    documents = {
        "employees.json": {"meta": meta, "employees": [profile, profile | {"employee_id": "TEST_2", "career_goal": None}]},
        "events.json": {"meta": meta, "events": [
            event,
            event | {"event_id": "EV_NEXT", "title": "Another Course"},
            event | {"event_id": "EV_SESSION", "format": "online", "upcoming_sessions": ["2026-10-02"]},
            event | {"event_id": "EV_036", "title": "Public Speaking Club", "format": "offline", "upcoming_sessions": ["2026-10-01", "2026-10-08"]},
            event | {"event_id": "EV_MAND", "mandatory": True, "develops_skills": []},
        ]},
        "skills.json": {"meta": meta, "proficiency_scale": {str(n): str(n) for n in range(6)},
            "skills": [{"skill_id": "SK_TEST", "name": "Test Skill", "type": "hard", "category": "test", "description": "Fixture"}],
            "role_profiles": [{"role": "Engineer", "grade": grade, "required_skills": {"SK_TEST": level}, "critical_skills": ["SK_TEST"]}
                              for grade, level in [("Junior", 1), ("Middle", 2)]]},
    }
    for filename, payload in documents.items():
        (directory / filename).write_text(json.dumps(payload), encoding="utf-8")
    with (directory / "activity_history.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["record_id", "employee_id", "event_id", "date", "due_date", "status", "completion_pct", "score", "feedback_rating", "assigned_by"])
        writer.writerow(["R_1", "TEST_1", "EV_MAND", "2026-09-02", "2026-09-30", "completed", 100, "", "", "hr"])
        writer.writerow(["R_2", "TEST_1", "EV_MAND", "2026-09-03", "2026-09-30", "completed", 100, "", "", "hr"])
    return directory


@pytest.fixture
def settings(tmp_path, dataset_dir):
    config = Settings(db_path=tmp_path / "test.sqlite3", as_of_date=date(2026, 10, 1))
    import_dataset(dataset_dir, config.db_path)
    return config


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client
