import hashlib
import unittest
from pathlib import Path
from backend.app.engine import analyze, load_dataset

DATA = Path(__file__).resolve().parents[1] / 'data/private/career_quest_dataset'


@unittest.skipUnless((DATA / 'employees.json').exists(), 'Local dataset not supplied')
class DatasetValidationTests(unittest.TestCase):
    def test_all_profiles_and_candidates(self):
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.iterdir() if p.is_file()}
        data = load_dataset(DATA)
        events = {e['event_id']: e for e in data['events']}
        for employee in data['employees']:
            with self.subTest(employee=employee['employee_id']):
                result = analyze(employee, data['history'], data['events'], data['catalog'], data['as_of_date'])
                completed = {r['event_id'] for r in result['history'] if r['status'] == 'completed'}
                self.assertLessEqual(len(result['recommendations']), 3)
                for item in result['candidates']:
                    event = events[item['event_id']]
                    self.assertFalse(event['mandatory'])
                    self.assertTrue(event['event_id'] not in completed or event['event_id'] == 'EV_036')
                    self.assertIn(employee['role'], event['target_roles'])
                    self.assertIn(employee['grade'], event['target_grades'])
                    self.assertTrue(all(result['effective_skills'].get(k, 0) >= v for k,v in event['prerequisites'].items()))
                    self.assertTrue(event['format'] == 'self_paced' or any(day >= data['as_of_date'] for day in event['upcoming_sessions']))
                    self.assertGreaterEqual(item['readiness_after'], item['readiness_before'])
                    self.assertTrue(item['critic']['passed'])
                    self.assertGreaterEqual(item['critic']['factor_count'], 3)
                    b = item['score_breakdown']
                    self.assertAlmostEqual(sum(value for key,value in b.items() if key != 'final_score'), b['final_score'], places=6)
        self.assertEqual(hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.iterdir() if p.is_file()})
