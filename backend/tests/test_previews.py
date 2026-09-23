import pytest
from fastapi.testclient import TestClient

from backend.app.engine_port import DomainError
from backend.app.main import create_app
from backend.app.mock_engine import MockEngine
from backend.app.schemas import ActivityRequest, SkillGain
from backend.app.storage import Store
from backend.tests.conftest import sign_in

BASE = '/api/v1/employees/TEST_1'


def test_recommendation_cards_match_simulation(client):
    response = client.get(BASE + '/recommendations')
    assert response.status_code == 200
    result = response.json()
    assert len(result['items']) == 3
    assert result['skills_basis'] == 'current'
    assert result['assessed_on'] == '2026-09-01'
    assert result['is_fallback'] is False
    for item in result['items']:
        assert item['duration_hours'] == 2
        assert len(item['reasons']) == 3
        assert 'критический' in item['reasons'][1]
        assert item['score'] is None
        simulation = client.post(BASE + '/simulations', json={
            'event_id': item['event_id'], 'session_date': item['session_date'],
        }).json()
        assert simulation['skill_changes'] == item['skill_changes']
        assert simulation['session_date'] == item['session_date']
    assert client.get(BASE + '/completions').json()['items'] == []


def test_gain_caps_missing_skills_no_downgrade_and_empty(settings):
    store = Store(settings.db_path)
    with store.connect() as db:
        ctx = store.context(db, 'TEST_1', settings.as_of_date)
    engine = MockEngine()
    ctx.events = [next(event for event in ctx.events if event.event_id == 'EV_SELF')]
    event = ctx.events[0]
    event.develops_skills[0].gain = 5
    result = engine.simulate(ctx, ActivityRequest(event_id=event.event_id))
    assert result.skills_after['SK_TEST'] == 3
    assert result.skill_changes[0].gain == 2
    ctx.profile.skills = {}
    result = engine.simulate(ctx, ActivityRequest(event_id=event.event_id))
    assert result.skills_before == {'SK_TEST': 0}
    assert result.skills_after == {'SK_TEST': 3}
    assert ctx.profile.skills == {}
    ctx.profile.skills = {'SK_TEST': 5}
    assert engine.recommend(ctx).items == []
    with pytest.raises(DomainError) as rejected:
        engine.simulate(ctx, ActivityRequest(event_id=event.event_id))
    assert rejected.value.status == 409
    extra = ctx.catalog.skills[0].model_copy(update={'skill_id': 'SK_NEW', 'name': 'New Skill'})
    ctx.catalog.skills.append(extra)
    event.develops_skills.append(SkillGain(skill_id='SK_NEW', gain=1, max_level=2))
    result = engine.simulate(ctx, ActivityRequest(event_id=event.event_id))
    assert result.skills_after == {'SK_TEST': 5, 'SK_NEW': 1}
    assert [row.gain for row in result.skill_changes] == [0, 1]
    assert ctx.profile.skills == {'SK_TEST': 5}


@pytest.mark.parametrize('failure', [TimeoutError(), DomainError(503, 'engine_unavailable', 'Try later')])
def test_preview_fallback_keeps_validation_authorization_and_no_writes(settings, failure):
    class UnavailableEngine(MockEngine):
        mode = 'live'

        def recommend(self, context):
            raise failure

        def simulate(self, context, request):
            raise failure

    with TestClient(create_app(settings, UnavailableEngine())) as client:
        sign_in(client)
        before = client.get(BASE).json()
        history = client.get(BASE + '/history').json()
        recommendations = client.get(BASE + '/recommendations').json()
        simulation = client.post(BASE + '/simulations', json={'event_id': 'EV_SELF'}).json()
        for result in [recommendations, simulation]:
            assert result['is_fallback'] is True
            assert result['mode'] == 'mock'
            assert result['skills_basis'] == 'current'
            assert result['fallback_reason']
        assert simulation['skills_after'] == {'SK_TEST': 2}
        assert client.post(BASE + '/simulations', json={'event_id': 'EV_MAND'}).status_code == 409
        assert client.post(BASE + '/simulations', json={'event_id': 'missing'}).status_code == 404
        assert client.get('/api/v1/employees/TEST_2/recommendations').status_code == 403
        assert client.post('/api/v1/employees/TEST_2/simulations', json={'event_id': 'EV_SELF'}).status_code == 403
        assert client.get(BASE).json() == before
        assert client.get(BASE + '/history').json() == history
        assert client.get(BASE + '/completions').json()['items'] == []


def test_domain_rejection_is_not_disguised_as_fallback(settings):
    class RejectingEngine(MockEngine):
        def simulate(self, context, request):
            raise DomainError(409, 'event_unavailable', 'Not available')

    with TestClient(create_app(settings, RejectingEngine())) as client:
        sign_in(client)
        response = client.post(BASE + '/simulations', json={'event_id': 'EV_SELF'})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'event_unavailable'
