import copy
import unittest

from backend.app.engine import analyze, simulate


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.employee = {"employee_id": "NEW", "role": "Engineer", "grade": "Middle",
                         "skills": {"design": 2, "speaking": 0}, "last_review_date": "2026-09-01"}
        self.catalog = {"skills": [{"skill_id": "design", "name": "Design"},
                                   {"skill_id": "speaking", "name": "Speaking"}],
                        "role_profiles": [{"role": "Engineer", "grade": "Senior",
                                           "required_skills": {"design": 4, "speaking": 2},
                                           "critical_skills": ["design"]}]}
        self.events = [self.event("DESIGN", "design"), self.event("TALK", "speaking")]

    def event(self, identifier, skill):
        return {"event_id": identifier, "title": identifier, "mandatory": False,
                "target_roles": ["Engineer"], "target_grades": ["Middle"],
                "prerequisites": {}, "format": "online", "duration_hours": 4,
                "upcoming_sessions": ["2026-10-10"],
                "develops_skills": [{"skill_id": skill, "gain": 1, "max_level": 4}]}

    def row(self, identifier, event, status, day="2026-09-10"):
        return {"record_id": identifier, "employee_id": "NEW", "event_id": event,
                "status": status, "date": day}

    def run_engine(self, history=()):
        return analyze(self.employee, history, self.events, self.catalog, "2026-10-01")

    def test_critical_gap_wins_over_lowest_skill_and_negative_history(self):
        rows = [self.row(str(i), "TALK", "no_show") for i in range(3)]
        result = self.run_engine(rows)
        self.assertEqual(result["recommendations"][0]["event_id"], "DESIGN")
        self.assertEqual(result["recommendations"][1]["facts"]["similar_negative"], 3)

    def test_review_boundary_and_duplicate_completion(self):
        rows = [self.row("a", "DESIGN", "completed", "2026-08-30"),
                self.row("b", "TALK", "completed"), self.row("c", "TALK", "completed")]
        result = self.run_engine(rows)
        self.assertEqual(result["effective_skills"], {"design": 2, "speaking": 1})
        self.assertFalse(result["recommendations"])

    def test_simulation_is_pure_and_caps_do_not_reduce_skill(self):
        original = copy.deepcopy(self.employee)
        self.events[0]["develops_skills"].append({"skill_id": "speaking", "gain": 1, "max_level": 1})
        self.employee["skills"]["speaking"] = 3
        result = simulate(self.employee, [], self.events, self.catalog, "2026-10-01", "DESIGN")
        self.assertEqual(result["skills_after"], {"design": 3, "speaking": 3})
        self.assertEqual(self.employee["skills"]["design"], original["skills"]["design"])

    def test_unavailable_events_are_excluded(self):
        self.events[0]["prerequisites"] = {"design": 5}
        self.events[1]["mandatory"] = True
        self.assertFalse(self.run_engine()["recommendations"])
        with self.assertRaises(ValueError):
            simulate(self.employee, [], self.events, self.catalog, "2026-10-01", "DESIGN")

    def test_imported_profile_unknown_goal_is_rejected(self):
        self.employee["career_goal"] = {"target_role": "Missing", "target_grade": "Senior"}
        with self.assertRaises(ValueError):
            self.run_engine()


if __name__ == "__main__":
    unittest.main()
