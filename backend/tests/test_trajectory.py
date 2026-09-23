from backend.app.mock_engine import MockEngine
from backend.app.schemas import CareerGoal, RoleProfile
from backend.app.storage import Store
from backend.tests.conftest import sign_in


def test_goal_requirements_and_snapshot_basis(client):
    response = client.get('/api/v1/employees/TEST_1/trajectory')
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'target_set'
    assert result['skills_basis'] == 'current'
    assert result['assessed_on'] == '2026-09-01'
    assert result['progress_pct'] is None
    assert result['met_count'] == 0
    assert result['critical_gap_count'] == 1
    assert result['requirements'][0] == {
        'skill_id': 'SK_TEST', 'name': 'Test Skill', 'type': 'hard',
        'current_level': 1, 'required_level': 2, 'gap': 1, 'critical': True,
    }


def test_no_goal_is_explicit_without_inventing_next_grade(client):
    sign_in(client, 'employee2')
    result = client.get('/api/v1/employees/TEST_2/trajectory').json()
    assert result['status'] == 'no_goal'
    assert result['target'] is None
    assert result['requirements'] == []
    assert result['critical_gap_count'] == 0


def test_missing_skill_higher_skill_and_role_change(settings):
    store = Store(settings.db_path)
    with store.connect() as db:
        ctx = store.context(db, 'TEST_1', settings.as_of_date)
    engine = MockEngine()
    ctx.profile.skills = {}
    assert engine.trajectory(ctx).requirements[0].gap == 2
    ctx.profile.skills = {'SK_TEST': 5}
    result = engine.trajectory(ctx)
    assert result.requirements[0].gap == 0
    assert result.requirements[0].current_level == 5
    assert result.met_count == 1 and result.critical_gap_count == 0
    ctx.profile.career_goal = CareerGoal(target_role='Manager', target_grade='Lead')
    assert engine.trajectory(ctx).status == 'target_unavailable'
    ctx.catalog.role_profiles.append(RoleProfile(role='Manager', grade='Lead', required_skills={'SK_TEST': 4}, critical_skills=[]))
    result = engine.trajectory(ctx)
    assert result.target.target_role == 'Manager'
    assert result.requirements[0].required_level == 4
    ctx.profile.grade = 'Lead'
    ctx.profile.career_goal = None
    assert engine.trajectory(ctx).status == 'no_goal'
