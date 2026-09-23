"""Reconstruct skills from the last review and completed history."""
from datetime import date
from .simulator import apply_gain

GRADES = ("Junior", "Middle", "Senior", "Lead")
REPEATABLE = "EV_036"

def build_state(employee, history, events, catalog, as_of_date):
    date.fromisoformat(as_of_date)
    if employee["grade"] not in GRADES:
        raise ValueError("Unknown employee grade")
    known_skills = {item["skill_id"] for item in catalog["skills"]}
    for skill, level in employee["skills"].items():
        if skill not in known_skills or type(level) is not int or not 0 <= level <= 5:
            raise ValueError(f"Invalid employee skill: {skill}")
    review = employee["last_review_date"]
    date.fromisoformat(review)
    if review > as_of_date:
        raise ValueError("Review date is later than calculation date")
    rows = sorted((row for row in history if row["employee_id"] == employee["employee_id"]),
                  key=lambda row: (row["date"], row["record_id"]))
    by_id = {event["event_id"]: event for event in events}
    seen = set()
    completed = set()
    levels = dict(employee["skills"])
    warnings = []
    valid_rows = []
    for row in rows:
        date.fromisoformat(row["date"])
        if row['status'] not in ('completed', 'in_progress', 'dropped', 'no_show', 'declined', 'overdue'):
            raise ValueError(f"Unknown history status: {row['status']}")
        if row["event_id"] not in by_id:
            raise ValueError(f"Unknown history event: {row['event_id']}")
        if row["record_id"] in seen:
            raise ValueError(f"Duplicate history record: {row['record_id']}")
        seen.add(row["record_id"])
        if row["date"] > as_of_date:
            continue
        valid_rows.append(row)
        if row["status"] != "completed":
            continue
        event = by_id[row["event_id"]]
        already_done = event["event_id"] in completed
        completed.add(event["event_id"])
        if already_done and event["event_id"] != REPEATABLE and not event["mandatory"]:
            warnings.append(f"Ignored repeated completion: {row['record_id']}")
            continue
        if event["format"] == "self_paced" and event["develops_skills"]:
            warnings.append(f"Completion date unavailable; enrollment date used: {row['record_id']}")
        if row["date"] > review:
            levels = apply_gain(levels, event)
    goal = employee.get("career_goal")
    if not goal:
        index = GRADES.index(employee["grade"])
        goal = {"target_role": employee["role"],
                "target_grade": GRADES[min(index + 1, len(GRADES) - 1)]}
        if employee["grade"] == "Lead":
            warnings.append("No higher grade; using current Lead requirements")
    target = next((profile for profile in catalog["role_profiles"]
                   if profile["role"] == goal["target_role"]
                   and profile["grade"] == goal["target_grade"]), None)
    if target is None:
        raise ValueError("No role profile for career target")
    return levels, target, valid_rows, completed, warnings
