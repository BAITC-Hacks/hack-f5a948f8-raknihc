import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import test_engine
from backend.app.engine.llm_explainer import explain_with_llm, verified_payload
from backend.app.engine.explainer import card_options


class ExplainerTests(unittest.TestCase):
    def setUp(self):
        fixture = test_engine.EngineTests()
        fixture.setUp()
        self.best, self.second = fixture.run_engine()['recommendations']

    def fake_client(self, output=None, error=None, status='completed'):
        factory = MagicMock()
        client = factory.return_value.__enter__.return_value
        client.responses.create.side_effect = error
        client.responses.create.return_value = SimpleNamespace(status=status, output_text=output)
        return factory, client

    def test_missing_key_does_not_call_sdk(self):
        factory, client = self.fake_client()
        with patch.dict('os.environ', {}, clear=True), patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=factory)}):
            result = explain_with_llm(self.best, self.second, enabled=True)
        self.assertEqual(result['fallback_reason'], 'missing_api_key')
        factory.assert_not_called()

    def test_disabled_does_not_call_sdk_even_with_key(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-placeholder'}):
            self.assertEqual(explain_with_llm(self.best)['fallback_reason'], 'disabled')

    def test_valid_output_and_minimized_payload(self):
        output = {k: v[1] for k,v in card_options(self.best, self.second).items()}
        factory, client = self.fake_client(json.dumps(output))
        original = copy.deepcopy(self.best)
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-placeholder'}), patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=factory)}):
            result = explain_with_llm(self.best, self.second, enabled=True)
        self.assertEqual(result['source'], 'openai')
        self.assertEqual(self.best, original)
        self.assertEqual(factory.call_args.kwargs, {'timeout': 5.0, 'max_retries': 0})
        request = client.responses.create.call_args.kwargs
        self.assertFalse(request['store'])
        self.assertNotIn('test-placeholder', request['input'])
        self.assertNotIn('full_name', request['input'])
        self.assertNotIn('employee_id', request['input'])

    def test_timeout_and_api_error_fall_back_without_exception_text(self):
        for error in (TimeoutError('private-request-details'), RuntimeError('private-request-details')):
            factory, _ = self.fake_client(error=error)
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-placeholder'}), patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=factory)}):
                result = explain_with_llm(self.best, self.second, enabled=True)
            self.assertEqual(result['source'], 'deterministic')
            self.assertNotIn('private-request-details', json.dumps(result))

    def test_malformed_invented_or_incomplete_output_falls_back(self):
        valid = {k:v[0] for k,v in card_options(self.best, self.second).items()}
        invalid = {**valid, 'why_this': 'Guaranteed promotion and 999 skill points'}
        for output, status in [('not json', 'completed'), ('[]', 'completed'),
                               (json.dumps(invalid), 'completed'), (json.dumps(valid), 'incomplete')]:
            factory, _ = self.fake_client(output, status=status)
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-placeholder'}), patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=factory)}):
                result = explain_with_llm(self.best, self.second, enabled=True)
            self.assertEqual(result['source'], 'deterministic')

    def test_missing_sdk_falls_back(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-placeholder'}), patch.dict('sys.modules', {'openai': None}):
            self.assertEqual(explain_with_llm(self.best, enabled=True)['source'], 'deterministic')

    def test_unverified_candidate_never_sent(self):
        self.best['critic']['passed'] = False
        with self.assertRaises(ValueError):
            verified_payload(self.best)
