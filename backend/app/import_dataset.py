"""Explicit, atomic, non-destructive import of the supplied JSON/CSV dataset."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from .config import Settings
from .schemas import Catalog, Employee, Event, HistoryRecord
from .storage import Store

FILES = ("employees.json", "events.json", "skills.json", "activity_history.csv")


def unique(values, label):
    values = list(values)
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")
    return set(values)


def load_dataset(directory: Path):
    raw = {name: (directory / name).read_bytes() for name in FILES}
    employees_doc = json.loads(raw["employees.json"])
    events_doc = json.loads(raw["events.json"])
    skills_doc = json.loads(raw["skills.json"])
    dates = {doc["meta"]["as_of_date"] for doc in (employees_doc, events_doc, skills_doc)}
    if len(dates) != 1:
        raise ValueError("Dataset as_of_date values disagree")
    employees = [Employee.model_validate(p) for p in employees_doc["employees"]]
    events = [Event.model_validate(e) for e in events_doc["events"]]
    catalog = Catalog.model_validate({key: skills_doc[key] for key in ("proficiency_scale", "skills", "role_profiles")})
    history = []
    reader = csv.DictReader(raw["activity_history.csv"].decode("utf-8-sig").splitlines())
    expected = set(HistoryRecord.model_fields) - {"completed_at"}
    if reader.fieldnames is None or set(reader.fieldnames) != expected or len(reader.fieldnames) != len(expected):
        raise ValueError("Unexpected activity_history.csv columns")
    for row in reader:
        if None in row:
            raise ValueError("Malformed activity_history.csv row")
        history.append(HistoryRecord.model_validate({k: v if v != "" else None for k, v in row.items()}))
    employee_ids = unique((p.employee_id for p in employees), "employee_id")
    event_ids = unique((e.event_id for e in events), "event_id")
    skill_ids = unique((s.skill_id for s in catalog.skills), "skill_id")
    role_keys = unique(((p.role, p.grade) for p in catalog.role_profiles), "role/grade")
    unique((h.record_id for h in history), "record_id")
    for p in employees:
        if (p.role, p.grade) not in role_keys or set(p.skills) - skill_ids:
            raise ValueError(f"Unknown role/grade/skill in {p.employee_id}")
        if p.manager_id is not None and p.manager_id not in employee_ids:
            raise ValueError(f"Unknown manager in {p.employee_id}")
        if p.career_goal and (p.career_goal.target_role, p.career_goal.target_grade) not in role_keys:
            raise ValueError(f"Unknown career goal in {p.employee_id}")
    for p in catalog.role_profiles:
        if set(p.required_skills) - skill_ids or set(p.critical_skills) - set(p.required_skills):
            raise ValueError(f"Unknown required/critical skill in {p.role}/{p.grade}")
    for e in events:
        if set(e.prerequisites) - skill_ids or {g.skill_id for g in e.develops_skills} - skill_ids:
            raise ValueError(f"Unknown skill in {e.event_id}")
        if any(not any(role == key[0] for key in role_keys) for role in e.target_roles):
            raise ValueError(f"Unknown target role in {e.event_id}")
    for h in history:
        if h.employee_id not in employee_ids or h.event_id not in event_ids:
            raise ValueError(f"Broken reference in {h.record_id}")
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode() + b"\0" + raw[name] + b"\0")
    return employees, events, catalog, history, digest.hexdigest(), dates.pop()


def import_dataset(directory: Path, db_path: Path):
    employees, events, catalog, history, digest, as_of_date = load_dataset(directory)
    store = Store(db_path)
    store.initialize()
    counts = dict(employees=len(employees), events=len(events), skills=len(catalog.skills), history=len(history))
    with store.connect(write=True) as db:
        existing = db.execute("SELECT value FROM metadata WHERE key='dataset_digest'").fetchone()
        if existing:
            if existing["value"] != digest:
                raise ValueError("A different dataset is already imported. Use a new database; existing data was not changed.")
            return counts | {"imported": False}
        if db.execute("SELECT 1 FROM employees LIMIT 1").fetchone():
            raise ValueError("Database contains profiles without import metadata; use a new database")
        db.executemany("INSERT INTO employees VALUES (?,?)", [(e.employee_id, e.model_dump_json()) for e in employees])
        db.executemany("INSERT INTO events VALUES (?,?)", [(e.event_id, e.model_dump_json()) for e in events])
        db.executemany("INSERT INTO history VALUES (?,?,?,?,?,?)", [
            (h.record_id, h.employee_id, h.event_id, h.date.isoformat(), h.status, h.model_dump_json()) for h in history])
        db.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("catalog", catalog.model_dump_json()), ("dataset_digest", digest), ("dataset_as_of_date", as_of_date)])
    return counts | {"imported": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--db", type=Path, default=Settings.from_env().db_path)
    args = parser.parse_args()
    try:
        result = import_dataset(args.directory, args.db)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Import failed: {exc}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
