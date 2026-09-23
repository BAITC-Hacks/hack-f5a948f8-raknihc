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

    def test_availability_and_prerequisite_boundaries(self):
        self.events[0]['upcoming_sessions'] = ['2026-09-30']
        self.events[1]['format'] = 'self_paced'
        self.events[1]['upcoming_sessions'] = []
        self.events[1]['prerequisites'] = {'design': 2}
        self.assertEqual([x['event_id'] for x in self.run_engine()['recommendations']], ['TALK'])
        self.events[0]['upcoming_sessions'] = ['2026-10-01']
        self.assertEqual(len(self.run_engine()['recommendations']), 2)

    def test_repeatable_club_and_in_progress_are_distinct(self):
        self.events[1]['event_id'] = 'EV_036'
        rows = [self.row('1', 'EV_036', 'completed')]
        self.assertIn('EV_036', [x['event_id'] for x in self.run_engine(rows)['recommendations']])
        rows.append(self.row('2', 'EV_036', 'in_progress', '2026-09-20'))
        self.assertNotIn('EV_036', [x['event_id'] for x in self.run_engine(rows)['recommendations']])

    def test_twin_readiness_and_critic_without_history(self):
        result = self.run_engine()
        item = result['recommendations'][0]
        self.assertEqual(item['readiness_before'], 33.33)
        self.assertEqual(item['readiness_after'], 50.0)
        self.assertTrue(item['critic']['passed'])
        self.assertEqual(item['critic']['factor_count'], 3)
        self.assertNotIn('participation', item['critic']['independent_factors'])
        self.assertEqual(item['counterfactual']['alternative_event_id'], 'TALK')

    def test_critic_rejects_missing_and_fabricated_evidence(self):
        from backend.app.engine.critic import critique
        item = self.run_engine()['recommendations'][0]
        del item['factors']['eligibility']
        audit = critique(item, self.employee, self.catalog['role_profiles'][0], [], self.events, '2026-10-01')
        self.assertFalse(audit['passed'])
        item = self.run_engine()['recommendations'][0]
        item['score_components']['critical_bonus'] = 100
        item['score'] = sum(item['score_components'].values())
        self.assertFalse(critique(item, self.employee, self.catalog['role_profiles'][0], [], self.events, '2026-10-01')['passed'])

    def test_career_change_and_next_grade_are_separate(self):
        profile = {'role': 'Analyst', 'grade': 'Middle', 'required_skills': {'speaking': 3}, 'critical_skills': []}
        self.catalog['role_profiles'].append(profile)
        self.employee['career_goal'] = {'target_role': 'Analyst', 'target_grade': 'Middle'}
        result = self.run_engine()
        self.assertEqual(result['target'], {'role': 'Analyst', 'grade': 'Middle'})
        self.assertEqual(result['next_grade_target'], {'role': 'Engineer', 'grade': 'Senior'})
        item = result['recommendations'][0]
        self.assertEqual(item['readiness_before'], 0)
        self.assertEqual(item['next_grade_readiness_before'], 33.33)

    def test_no_mutation_and_completion_recalculates_trajectory(self):
        original = copy.deepcopy((self.employee, self.events, self.catalog))
        first = self.run_engine()
        second = self.run_engine([self.row('1', 'DESIGN', 'completed')])
        self.assertGreater(second['readiness_before'], first['readiness_before'])
        self.assertEqual(second['effective_skills']['design'], 3)
        self.assertNotIn('DESIGN', [x['event_id'] for x in second['recommendations']])
        first['candidates'][0]['factors']['eligibility']['target_roles'].append('Other')
        self.assertEqual((self.employee, self.events, self.catalog), original)

    def test_tie_explanation_and_no_alternative(self):
        self.events.append(copy.deepcopy(self.events[0]))
        self.events[-1]['event_id'] = 'DESIGN2'
        first = self.run_engine()['recommendations'][0]
        self.assertEqual(first['counterfactual']['score_margin'], 0)
        self.assertIn('event_id', first['counterfactual']['why_not'])
        self.events = self.events[:1]
        self.assertIsNone(self.run_engine()['recommendations'][0]['counterfactual']['alternative_event_id'])

    def test_goal_bonus_is_supported_by_real_target_profile(self):
        baseline = self.run_engine()['recommendations'][0]
        self.assertEqual(baseline['factors']['career_goal']['status'], 'unavailable')
        self.employee['career_goal'] = {'target_role': 'Engineer', 'target_grade': 'Senior'}
        candidate = self.run_engine()['recommendations'][0]
        self.assertEqual(candidate['factors']['career_goal']['status'], 'applied')
        self.assertGreater(candidate['score_breakdown']['career_goal_modifier'], 0)
        self.assertGreater(candidate['score'], baseline['score'])

    def test_critical_next_grade_survives_role_change(self):
        self.catalog['role_profiles'].append({'role': 'Analyst', 'grade': 'Middle',
                                             'required_skills': {'speaking': 3}, 'critical_skills': []})
        self.employee['career_goal'] = {'target_role': 'Analyst', 'target_grade': 'Middle'}
        result = self.run_engine()
        design = next(x for x in result['candidates'] if x['event_id'] == 'DESIGN')
        self.assertEqual(design['factors']['career_goal']['status'], 'not_applicable')
        self.assertEqual(design['score_breakdown']['career_goal_modifier'], 0)
        self.assertEqual(design['score_breakdown']['critical_gap_impact'], 2)

    def test_efficiency_is_small_and_negative_history_is_not_veto(self):
        self.events[0]['duration_hours'] = 40
        self.events[1]['duration_hours'] = 1
        rows = [self.row(str(i), 'DESIGN', 'no_show') for i in range(3)]
        result = self.run_engine(rows)
        self.assertEqual(result['recommendations'][0]['event_id'], 'DESIGN')
        self.assertLess(result['recommendations'][0]['score_breakdown']['history_modifier'], 0)
        for item in result['candidates']:
            self.assertLessEqual(item['score_breakdown']['efficiency_modifier'], 0.2)
        self.events[0]['prerequisites'] = {'design': 5}
        rows = [self.row('skip', 'TALK', 'no_show')]
        self.assertEqual(self.run_engine(rows)['recommendations'][0]['event_id'], 'TALK')

    def test_no_candidate_has_reason(self):
        for event in self.events:
            event['prerequisites'] = {'design': 5}
        result = self.run_engine()
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(result['no_recommendation_reason'], 'no_eligible_gap_closing_event')

    def test_close_candidates_compare_exact_breakdown(self):
        self.events.append(copy.deepcopy(self.events[0]))
        self.events[-1]['event_id'] = 'DESIGN2'
        self.events[-1]['duration_hours'] = 5
        result = self.run_engine()
        best, second = result['recommendations'][:2]
        comparison = best['counterfactual']
        self.assertGreater(comparison['component_deltas']['efficiency_modifier'], 0)
        self.assertIn('efficiency_modifier', comparison['why_not'])
        self.assertAlmostEqual(comparison['score_margin'], best['score'] - second['score'], places=4)

    def test_critic_checks_requirements_criticality_and_real_gain(self):
        from backend.app.engine.critic import critique
        item = self.run_engine()['recommendations'][0]
        categories = {x['category'] for x in item['critic']['evidence_categories']}
        self.assertIn('criticality_or_career_relevance', categories)
        self.assertIn('requirement_skill_gap', categories)
        self.assertTrue(item['critic']['warnings'])
        item['skills_after']['design'] = 5
        self.assertFalse(critique(item, self.employee, self.catalog['role_profiles'][0], [], self.events, '2026-10-01')['passed'])


if __name__ == "__main__":
    unittest.main()
