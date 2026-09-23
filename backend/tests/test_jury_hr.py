import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.engine_port import DomainError
from backend.app.mock_engine import MockEngine
from backend.app.schemas import HistoryRecord
from backend.tests.conftest import sign_in, TEST_PASSWORD

BASE = '/api/v1/employees/TEST_1'


def csv_rows(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(HistoryRecord.model_fields))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def profile(client, id='JURY_1'):
    return client.get(BASE).json() | {'employee_id': id, 'full_name': 'Jury Employee'}


def record(id='J_1', employee='JURY_1', event='EV_SELF', day='2026-10-01'):
    return dict(record_id=id, employee_id=employee, event_id=event, date=day, due_date='',
                status='completed', completion_pct=100, score='', feedback_rating='', assigned_by='self', completed_at=day)


def test_import_preview_atomic_save_replay_and_immediate_engine_hr_visibility(client):
    new = profile(client)
    body = {'employees_json': json.dumps({'employees': [new]}), 'history_csv': csv_rows([record()])}
    assert client.post('/api/v1/hr/imports', json=body).status_code == 403
    assert client.get('/api/v1/hr/overview').status_code == 403
    sign_in(client, 'hr')
    preview = client.post('/api/v1/hr/imports', json=body)
    assert preview.status_code == 200
    assert preview.json()['dry_run'] is True
    assert client.get('/api/v1/employees/JURY_1').status_code == 404
    body['dry_run'] = False
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/v1/hr/imports', json=body), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()['history_added'] for response in responses) == [0, 1]
    assert sorted(response.json()['employees_added'] for response in responses) == [0, 1]
    base = '/api/v1/employees/JURY_1'
    assert client.get(base + '/trajectory').json()['current_skills'] == {'SK_TEST': 2}
    assert 'EV_SELF' not in [item['event_id'] for item in client.get(base + '/recommendations').json()['items']]
    overview = client.get('/api/v1/hr/overview').json()
    assert len(overview['employees']) == 3
    assert any(row['employee_id'] == 'JURY_1' for row in overview['employees'])
    event = next(row for row in overview['events'] if row['event_id'] == 'EV_SELF')
    assert event['participants'] == event['completed'] == event['records'] == 1
    replay = client.post('/api/v1/hr/imports', json=body).json()
    assert replay['employees_skipped'] == replay['history_skipped'] == 1
    # Imported users may be bound through the existing administrator CLI/service.
    client.app.state.auth.create_user('jury1', TEST_PASSWORD, 'employee', 'JURY_1')
    sign_in(client, 'jury1')
    assert client.get(base).status_code == 200
    assert client.get(BASE).status_code == 403


def test_bad_import_is_atomic_and_reports_row_field(client):
    new = profile(client)
    sign_in(client, 'hr')
    for body in [
        {'employees_json': '{bad json'},
        {'employees_json': json.dumps([new | {'skills': {'SK_TEST': 9}}])},
        {'employees_json': json.dumps([new | {'skills': {'UNKNOWN': 1}}])},
        {'employees_json': json.dumps([new | {'manager_id': 'absent'}])},
        {'employees_json': json.dumps([new, new])},
        {'employees_json': json.dumps([new]), 'history_csv': csv_rows([record(event='absent')])},
        {'employees_json': json.dumps([new]), 'history_csv': csv_rows([record(employee='absent')])},
        {'history_csv': 'bad,header\n1,2'},
        {'employees_json': json.dumps([new]), 'history_csv': csv_rows([record(), record('J_2')])},
        {'employees_json': json.dumps([new]), 'history_csv': csv_rows([record(day='2026-10-02')])},
        {'employees_json': json.dumps([new | {'employee_id': 'TEST_1'}])},
    ]:
        response = client.post('/api/v1/hr/imports', json=body | {'dry_run': False})
        assert response.status_code == 422, response.text
        issue = response.json()['detail']['issues'][0]
        assert set(issue) == {'file', 'row', 'field', 'message'}
        assert issue['message']
        assert client.get('/api/v1/employees/JURY_1').status_code == 404
        assert client.get('/api/v1/hr/summary').json()['history_records_total'] == 2


def test_completion_updates_skills_once_and_club_sessions_accumulate(client, settings):
    old = client.get(BASE).json()
    body = {'event_id': 'EV_SELF'}
    first = client.post(BASE + '/completions', json=body, headers={'Idempotency-Key': 'done'})
    assert first.status_code == 201
    assert client.get(BASE + '/trajectory').json()['current_skills'] == {'SK_TEST': 2}
    assert client.post(BASE + '/completions', json=body, headers={'Idempotency-Key': 'done'}).status_code == 200
    assert client.post(BASE + '/completions', json=body, headers={'Idempotency-Key': 'other'}).status_code == 409
    assert client.get(BASE + '/trajectory').json()['current_skills'] == {'SK_TEST': 2}
    assert client.get(BASE).json() == old
    sign_in(client, 'hr')
    after = client.get('/api/v1/hr/overview').json()
    assert after['skill_gaps'] == []
    # Independent employee starts at level 1: two distinct club sessions -> level 3.
    sign_in(client, 'employee2')
    base = '/api/v1/employees/TEST_2'
    assert client.post(base + '/completions', json={'event_id': 'EV_036', 'session_date': '2026-10-01'}, headers={'Idempotency-Key': 'club1'}).status_code == 201
    assert client.get(base + '/trajectory').json()['current_skills'] == {'SK_TEST': 2}
    with TestClient(create_app(replace(settings, as_of_date=date(2026, 10, 8)), engine=MockEngine())) as later:
        sign_in(later, 'employee2')
        assert later.post(base + '/completions', json={'event_id': 'EV_036', 'session_date': '2026-10-08'}, headers={'Idempotency-Key': 'club2'}).status_code == 201
        assert later.get(base + '/trajectory').json()['current_skills'] == {'SK_TEST': 3}
        assert later.get(base + '/recommendations').json()['items'] == []
        sign_in(later, 'hr')
        overview = later.get('/api/v1/hr/overview').json()
        club = next(event for event in overview['events'] if event['event_id'] == 'EV_036')
        assert club['participants'] == 1 and club['completed'] == club['records'] == 2
        assert overview['no_step_count'] == 1


def test_history_import_cannot_duplicate_completion_and_respects_review_cutoff(client):
    client.post(BASE + '/completions', json={'event_id': 'EV_SELF'}, headers={'Idempotency-Key': 'app-done'})
    new = profile(client)
    sign_in(client, 'hr')
    response = client.post('/api/v1/hr/imports', json={'history_csv': csv_rows([record(employee='TEST_1')]), 'dry_run': False})
    assert response.status_code == 422
    assert 'Второе начисление' in response.json()['detail']['issues'][0]['message']
    history = [record('OLD', day='2026-08-30'), record('NEXT', event='EV_NEXT', day='2026-09-10')]
    response = client.post('/api/v1/hr/imports', json={'employees_json': json.dumps([new]), 'history_csv': csv_rows(history), 'dry_run': False})
    assert response.status_code == 200
    assert client.get('/api/v1/employees/JURY_1/trajectory').json()['current_skills'] == {'SK_TEST': 2}


def test_anonymous_import_and_hr_overview_rejected(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/v1/hr/imports', json={}).status_code == 401
        assert client.get('/api/v1/hr/overview').status_code == 401


def test_hr_distinguishes_engine_error_from_no_candidate(settings):
    class UnavailableEngine(MockEngine):
        def recommend(self, context):
            raise DomainError(503, 'engine_unavailable', 'Try later')

    with TestClient(create_app(settings, UnavailableEngine())) as client:
        sign_in(client, 'hr')
        result = client.get('/api/v1/hr/overview').json()
        assert result['no_step_count'] == 0
        assert result['unavailable_count'] == 2
        assert {row['recommendation_status'] for row in result['employees']} == {'unavailable'}


def test_import_byte_limit_and_body_defaults(client):
    sign_in(client, 'hr')
    response = client.post('/api/v1/hr/imports', json={'employees_json': 'я' * 1_000_001})
    assert response.status_code == 422
    assert '2 МБ' in response.json()['detail']['issues'][0]['message']
    assert client.post('/api/v1/hr/imports', json={}).status_code == 422
