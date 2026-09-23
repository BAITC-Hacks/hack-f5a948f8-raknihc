import copy
import json
import unittest
from unittest.mock import patch

from backend.app.engine import recommend, analyze
from test_jury import fixture


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        employee, catalog, events = fixture()
        self.args = (employee, [], events, catalog, '2026-10-01')

    def test_json_contract_and_frozen_algorithm(self):
        original = copy.deepcopy(self.args)
        result = recommend(*self.args)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertEqual(set(result), {'employee_id', 'current_grade', 'target', 'next_grade',
                                      'readiness_before', 'recommendations', 'no_recommendation_reason', 'warnings'})
        baseline = analyze(*self.args)
        for item, expected in zip(result['recommendations'], baseline['recommendations']):
            self.assertEqual(set(item), {'event_id', 'title', 'final_score', 'score_breakdown',
                             'skill_impacts', 'readiness_after', 'why_this', 'why_not',
                             'alternative_event_id', 'critic', 'explanation', 'explanation_source',
                             'fallback_reason', 'expected_career_impact', 'caution'})
            self.assertEqual(item['event_id'], expected['event_id'])
            self.assertEqual(item['final_score'], expected['score'])
            self.assertEqual(item['score_breakdown'], expected['score_breakdown'])
            self.assertEqual(item['readiness_after'], expected['readiness_after'])
            self.assertEqual(item['explanation_source'], 'deterministic')
            for impact in item['skill_impacts']:
                self.assertEqual(impact['after'], expected['skills_after'][impact['skill_id']])
                self.assertEqual(impact['gain'], impact['after'] - impact['before'])
        self.assertEqual(self.args, original)

    def test_limit_one_keeps_real_runner_up(self):
        result = recommend(*self.args, limit=1)
        self.assertEqual(len(result['recommendations']), 1)
        self.assertEqual(result['recommendations'][0]['alternative_event_id'], 'J_SPEAK')

    def test_missing_key_fallback_is_serializable(self):
        with patch.dict('os.environ', {}, clear=True):
            result = recommend(*self.args, use_llm=True)
        item = result['recommendations'][0]
        self.assertEqual(item['explanation_source'], 'deterministic')
        self.assertEqual(item['fallback_reason'], 'missing_api_key')
        json.dumps(result, allow_nan=False)

    def test_llm_source_mapping_keeps_ranking(self):
        from backend.app.engine.explainer import deterministic_card
        def mock_explainer(best, alternative, **kwargs):
            return {**deterministic_card(best, alternative), 'source': 'openai', 'fallback_reason': None}
        with patch('backend.app.engine.llm_explainer.explain_with_llm', side_effect=mock_explainer):
            result = recommend(*self.args, use_llm=True)
        self.assertEqual(result['recommendations'][0]['explanation_source'], 'llm')
        self.assertEqual(result['recommendations'][1]['explanation_source'], 'deterministic')
        json.dumps(result, allow_nan=False)

    def test_no_candidates_returns_empty_json_response(self):
        for event in self.args[2]:
            event['upcoming_sessions'] = []
        result = recommend(*self.args)
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(result['no_recommendation_reason'], 'no_eligible_gap_closing_event')
        json.dumps(result, allow_nan=False)

    def test_lead_without_next_grade(self):
        self.args[0]['grade'] = 'Lead'
        result = recommend(*self.args)
        self.assertIsNone(result['next_grade'])
        json.dumps(result, allow_nan=False)
