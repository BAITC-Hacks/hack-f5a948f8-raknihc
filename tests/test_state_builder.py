"""Regression tests for the last-review snapshot and completed event gains."""
import copy
import unittest

from backend.app.engine.state_builder import build_state
from test_jury import fixture, row


class StateBuilderTests(unittest.TestCase):
    def setUp(self):
        self.employee, self.catalog, self.events = fixture()
        self.skill = 'SK_SYSTEM_DESIGN'
        self.employee['skills'][self.skill] = 2
        self.employee['last_review_date'] = '2026-09-01'

    def completion(self, day, event='J_SYSTEM', identifier='R1'):
        return {**row(event, 'completed'), 'date': day, 'record_id': identifier}

    def state(self, history):
        return build_state(self.employee, history, self.events, self.catalog, '2026-10-01')[0]

    def test_completion_before_review_does_not_add_gain(self):
        self.assertEqual(self.state([self.completion('2026-08-31')])[self.skill], 2)

    def test_completion_on_review_does_not_add_gain(self):
        self.assertEqual(self.state([self.completion('2026-09-01')])[self.skill], 2)

    def test_completion_after_review_applies_gain(self):
        self.assertEqual(self.state([self.completion('2026-09-02')])[self.skill], 3)
        self.assertEqual(self.employee['skills'][self.skill], 2)

    def test_multiple_post_review_completions_apply_in_date_order(self):
        # A low-cap event must run first even when history arrives out of order.
        self.events[0]['develops_skills'][0]['max_level'] = 3
        second = copy.deepcopy(self.events[0])
        second['event_id'] = 'J_SYSTEM_ADVANCED'
        second['develops_skills'][0].update(gain=2, max_level=5)
        self.events.append(second)
        history = [self.completion('2026-09-20', second['event_id'], 'R2'),
                   self.completion('2026-09-02')]
        self.assertEqual(self.state(history)[self.skill], 5)

    def test_event_max_level_caps_gain(self):
        self.events[0]['develops_skills'][0].update(gain=4, max_level=3)
        self.assertEqual(self.state([self.completion('2026-09-02')])[self.skill], 3)

    def test_existing_level_above_event_cap_is_never_reduced(self):
        self.employee['skills'][self.skill] = 5
        self.events[0]['develops_skills'][0].update(gain=1, max_level=3)
        self.assertEqual(self.state([self.completion('2026-09-02')])[self.skill], 5)

    def test_repeatable_completions_across_review_boundary(self):
        self.events[0]['event_id'] = 'EV_036'
        history = [self.completion(day, 'EV_036', f'R{i}')
                   for i, day in enumerate(('2026-08-30', '2026-09-01', '2026-09-02', '2026-09-03'))]
        self.assertEqual(self.state(history)[self.skill], 4)

    def test_future_completion_is_not_applied(self):
        self.assertEqual(self.state([self.completion('2026-10-02')])[self.skill], 2)

    def test_uncompleted_post_review_activity_has_no_gain(self):
        record = {**self.completion('2026-09-02'), 'status': 'in_progress', 'completion_pct': '50'}
        self.assertEqual(self.state([record])[self.skill], 2)
