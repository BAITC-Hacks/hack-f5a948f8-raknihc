"""Deterministic baseline. Scores are heuristics, not promotion probabilities."""

import csv
import json
from datetime import date
from pathlib import Path

GRADES = ("Junior", "Middle", "Senior", "Lead")
REPEATABLE = "EV_036"


def load_dataset(directory):
    directory = Path(directory)
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))
    employees = read("employees.json")
    skills = read("skills.json")
    events = read("events.json")
    with (directory / "activity_history.csv").open(encoding="utf-8-sig", newline="") as file:
        history = list(csv.DictReader(file))
    return {"employees": employees["employees"], "history": history,
            "events": events["events"], "catalog": skills,
            "as_of_date": employees["meta"]["as_of_date"]}


def _gain(levels, event):
    result = dict(levels)
    for item in event["develops_skills"]:
        skill = item["skill_id"]
        old = result.get(skill, 0)
        result[skill] = max(old, min(5, item["max_level"], old + item["gain"]))
    return result


def _state(employee, history, events, catalog, as_of_date):
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
            levels = _gain(levels, event)
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


def _progress(levels, target):
    required = target["required_skills"]
    total = sum(required.values())
    return round(100 * sum(min(levels.get(key, 0), value)
                           for key, value in required.items()) / total, 2) if total else 100.0


def analyze(employee, history, events, catalog, as_of_date, limit=3):
    """Return JSON-compatible facts and up to three rule-ranked recommendations."""
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("limit must be an integer between 1 and 3")
    levels, target, rows, completed, warnings = _state(
        employee, history, events, catalog, as_of_date)
    names = {item["skill_id"]: item["name"] for item in catalog["skills"]}
    gaps = [{"skill_id": key, "name": names[key], "current": levels.get(key, 0),
             "required": value, "gap": value - levels.get(key, 0),
             "critical": key in target["critical_skills"]}
            for key, value in target["required_skills"].items() if levels.get(key, 0) < value]
    recommendations, excluded = [], []
    for event in events:
        event_id = event["event_id"]
        reasons = []
        event_rows = [row for row in rows if row["event_id"] == event_id]
        if event["mandatory"]:
            reasons.append("mandatory")
        if employee["role"] not in event["target_roles"] or employee["grade"] not in event["target_grades"]:
            reasons.append("audience_mismatch")
        if event_id in completed and event_id != REPEATABLE:
            reasons.append("already_completed")
        if event_rows and event_rows[-1]["status"] == "in_progress":
            reasons.append("already_in_progress")
        if any(levels.get(key, 0) < value for key, value in event["prerequisites"].items()):
            reasons.append("prerequisites_not_met")
        sessions = sorted(value for value in event["upcoming_sessions"] if value >= as_of_date)
        if event["format"] != "self_paced" and not sessions:
            reasons.append("no_future_session")
        after = _gain(levels, event)
        benefits = [{"skill_id": gap["skill_id"], "before": gap["current"],
                     "after": after.get(gap["skill_id"], 0), "required": gap["required"],
                     "critical": gap["critical"]} for gap in gaps
                    if after.get(gap["skill_id"], 0) > gap["current"]]
        if not benefits:
            reasons.append("no_target_gap_gain")
        if reasons:
            excluded.append({"event_id": event_id, "reasons": reasons})
            continue
        skills = {item["skill_id"] for item in event["develops_skills"]}
        similar_ids = {item["event_id"] for item in events
                       if skills.intersection(gain["skill_id"] for gain in item["develops_skills"])}
        recent = rows[-30:]
        similar = [row for row in recent if row["event_id"] in similar_ids]
        failures = sum(row["status"] in ("no_show", "dropped", "declined") for row in similar)
        successes = sum(row["status"] == "completed" for row in similar)
        penalty = failures / max(1, len(similar))
        benefit = sum(min(item["after"], item["required"]) - item["before"] for item in benefits)
        critical = sum(min(item["after"], item["required"]) - item["before"]
                       for item in benefits if item["critical"])
        score = round(benefit + 2 * critical - penalty + 0.1 * min(successes, 3), 4)
        facts = {"current_role": employee["role"], "current_grade": employee["grade"],
                 "target_role": target["role"], "target_grade": target["grade"],
                 "skill_changes": benefits, "similar_history_count": len(similar),
                 "similar_completed": successes, "similar_negative": failures}
        gap_text = "; ".join(f"{names[item['skill_id']]}: {item['before']} → {item['after']} "
                             f"при требовании {item['required']}" for item in benefits)
        explanation = (f"Для {employee['role']} ({employee['grade']}) с целью "
                       f"{target['role']} ({target['grade']}). {gap_text}. "
                       f"Среди последних 30 записей: похожих активностей — {len(similar)}, "
                       f"завершений — {successes}, пропусков/отказов/прекращений — {failures}.")
        recommendations.append({"event_id": event_id, "title": event["title"], "score": score,
                                "next_session": sessions[0] if sessions else None,
                                "duration_hours": event["duration_hours"], "facts": facts,
                                "explanation": explanation,
                                "progress_after_pct": _progress(after, target)})
    recommendations.sort(key=lambda item: (-item["score"], item["duration_hours"], item["event_id"]))
    return {"employee_id": employee["employee_id"], "as_of_date": as_of_date,
            "mode": "rules", "effective_skills": levels,
            "target": {"role": target["role"], "grade": target["grade"]},
            "progress_pct": _progress(levels, target), "gaps": gaps,
            "critical_gaps": [gap["skill_id"] for gap in gaps if gap["critical"]],
            "recommendations": recommendations[:limit], "excluded_events": excluded,
            "no_recommendation_reason": None if recommendations else "no_eligible_gap_closing_event",
            "warnings": warnings}


def simulate(employee, history, events, catalog, as_of_date, event_id):
    """Preview an eligible development activity; does not persist completion."""
    result = analyze(employee, history, events, catalog, as_of_date)
    rejected = next((item for item in result["excluded_events"] if item["event_id"] == event_id), None)
    if rejected:
        raise ValueError(f"Activity unavailable: {', '.join(rejected['reasons'])}")
    event = next((item for item in events if item["event_id"] == event_id), None)
    if event is None:
        raise ValueError("Unknown event")
    target = next(item for item in catalog["role_profiles"]
                  if item["role"] == result["target"]["role"] and item["grade"] == result["target"]["grade"])
    after = _gain(result["effective_skills"], event)
    return {"event_id": event_id, "skills_before": result["effective_skills"],
            "skills_after": after, "progress_before_pct": result["progress_pct"],
            "progress_after_pct": _progress(after, target)}
