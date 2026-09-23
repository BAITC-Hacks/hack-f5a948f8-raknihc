"""Adversarial profiles use the supplied dataset's JSON/CSV field schema."""
import copy
import unittest
from backend.app.engine import analyze


def fixture():
    employee = {'employee_id': 'JURY_A', 'full_name': 'Synthetic Jury Employee',
                'department': 'Backend Development', 'role': 'Backend Engineer', 'grade': 'Middle',
                'manager_id': None, 'hire_date': '2024-10-01', 'tenure_months': 24,
                'work_format': 'remote', 'preferred_language': 'en',
                'career_goal': {'target_role': 'Backend Engineer', 'target_grade': 'Senior'},
                'skills': {'SK_SYSTEM_DESIGN': 2, 'SK_PUBLIC_SPEAKING': 0},
                'last_review_date': '2026-09-01'}
    catalog = {'meta': {'as_of_date': '2026-10-01'},
               'proficiency_scale': {str(i): str(i) for i in range(6)},
               'skills': [{'skill_id': key, 'name': name, 'type': kind, 'category': kind, 'description': name}
                          for key, name, kind in [('SK_SYSTEM_DESIGN', 'System Design', 'hard'),
                                                   ('SK_PUBLIC_SPEAKING', 'Public Speaking', 'soft')]],
               'role_profiles': [{'role': 'Backend Engineer', 'grade': 'Senior',
                                  'required_skills': {'SK_SYSTEM_DESIGN': 4, 'SK_PUBLIC_SPEAKING': 2},
                                  'critical_skills': ['SK_SYSTEM_DESIGN']}]}
    def event(identifier, skill):
        return {'event_id': identifier, 'title': identifier, 'description': 'Synthetic activity',
                'type': 'workshop', 'format': 'online', 'duration_hours': 4, 'mandatory': False,
                'target_roles': ['Backend Engineer'], 'target_grades': ['Middle'],
                'develops_skills': [{'skill_id': skill, 'gain': 1, 'max_level': 4}],
                'prerequisites': {}, 'upcoming_sessions': ['2026-10-10']}
    return employee, catalog, [event('J_SYSTEM', 'SK_SYSTEM_DESIGN'), event('J_SPEAK', 'SK_PUBLIC_SPEAKING')]


def row(event_id, status):
    return {'record_id': 'J_RECORD', 'employee_id': 'JURY_A', 'event_id': event_id,
            'date': '2026-09-20', 'due_date': '', 'status': status,
            'completion_pct': '100' if status == 'completed' else '0',
            'score': '', 'feedback_rating': '', 'assigned_by': 'self'}


class JuryTests(unittest.TestCase):
    def setUp(self):
        self.employee, self.catalog, self.events = fixture()

    def run_profile(self, history=()):
        return analyze(self.employee, history, self.events, self.catalog, '2026-10-01')

    def test_A_lowest_skill_does_not_win(self):
        self.assertEqual(self.run_profile()['recommendations'][0]['event_id'], 'J_SYSTEM')

    def test_B_negative_history_is_modifier(self):
        top = self.run_profile([row('J_SYSTEM', 'no_show')])['recommendations'][0]
        self.assertEqual(top['event_id'], 'J_SYSTEM')
        self.assertEqual(top['score_breakdown']['history_modifier'], -1)

    def test_C_no_history_is_not_invented(self):
        top = self.run_profile()['recommendations'][0]
        self.assertTrue(top['critic']['passed'])
        self.assertFalse(top['critic']['history_evidence_available'])
        self.assertEqual(top['factors']['participation']['record_ids'], [])

    def test_D_completed_event_is_excluded(self):
        result = self.run_profile([row('J_SYSTEM', 'completed')])
        self.assertNotIn('J_SYSTEM', [x['event_id'] for x in result['candidates']])

    def test_E_prerequisite_failure_is_excluded(self):
        self.events[0]['prerequisites'] = {'SK_SYSTEM_DESIGN': 3}
        self.assertNotIn('J_SYSTEM', [x['event_id'] for x in self.run_profile()['candidates']])

    def test_F_empty_result_has_reason(self):
        for event in self.events:
            event['upcoming_sessions'] = []
        result = self.run_profile()
        self.assertEqual(result['recommendations'], [])
        self.assertIsNotNone(result['no_recommendation_reason'])

    def test_G_close_candidates_use_real_breakdown(self):
        self.events[1] = copy.deepcopy(self.events[0])
        self.events[1]['event_id'] = 'J_SYSTEM_ALTERNATIVE'
        self.events[1]['duration_hours'] = 5
        best, second = self.run_profile()['recommendations']
        comparison = best['counterfactual']
        self.assertIn('efficiency_modifier', comparison['why_not'])
        for key, delta in comparison['component_deltas'].items():
            self.assertAlmostEqual(delta, best['score_breakdown'][key] - second['score_breakdown'][key], places=6)
