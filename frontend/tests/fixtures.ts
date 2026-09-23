import type { Page } from '@playwright/test'

export const profile = {
  employee_id: 'E_TEST', full_name: 'Alex Test', department: 'Engineering', role: 'Backend Engineer', grade: 'Junior',
  manager_id: null, hire_date: '2025-04-15', tenure_months: 18, work_format: 'hybrid', preferred_language: 'ru',
  career_goal: { target_role: 'Backend Engineer', target_grade: 'Middle' },
  skills: { SK_API: 2, SK_TEAM: 3 }, last_review_date: '2026-09-01',
}
export const trajectory = {
  employee_id: 'E_TEST', as_of_date: '2026-10-01', assessed_on: '2026-09-01', mode: 'mock', skills_basis: 'last_review',
  target: profile.career_goal, status: 'target_set', progress_pct: null, met_count: 1, critical_gap_count: 1,
  requirements: [
    { skill_id: 'SK_API', name: 'API Design', type: 'hard', current_level: 2, required_level: 3, gap: 1, critical: true },
    { skill_id: 'SK_TEAM', name: 'Teamwork', type: 'soft', current_level: 3, required_level: 2, gap: 0, critical: false },
  ], message: 'Assessment snapshot',
}
export const catalog = {
  proficiency_scale: { '0': 'None', '1': 'Basic' }, role_profiles: [],
  skills: [
    { skill_id: 'SK_API', name: 'API Design', type: 'hard', category: 'engineering', description: 'Designing reliable interfaces.' },
    { skill_id: 'SK_TEAM', name: 'Teamwork', type: 'soft', category: 'people', description: 'Working well together.' },
  ],
}
export const events = { items: [
  { event_id: 'EV_A', title: 'Architecture Fundamentals', format: 'online', duration_hours: 12, mandatory: false },
  { event_id: 'EV_B', title: 'Team Workshop', format: 'self_paced', duration_hours: 4, mandatory: false },
] }
export const history = { items: [
  { record_id: 'R_A', employee_id: 'E_TEST', event_id: 'EV_A', date: '2026-09-10', due_date: null, status: 'completed', completion_pct: 100, score: 0, feedback_rating: null, assigned_by: 'self', completed_at: null },
  { record_id: 'R_B', employee_id: 'E_TEST', event_id: 'EV_B', date: '2026-09-12', due_date: null, status: 'in_progress', completion_pct: 40, score: null, feedback_rating: null, assigned_by: 'self', completed_at: null },
] }
export async function mockApi(page: Page, options: { noGoal?: boolean; emptyHistory?: boolean; hr?: boolean; failFirst?: boolean } = {}) {
  const seen: string[] = []
  let failed = false
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    seen.push(path)
    const send = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === '/auth/login') {
      const body = route.request().postDataJSON()
      if (body.password !== 'test-password') return send({ detail: { code: 'invalid_credentials' } }, 401)
      return send({ access_token: 'test-session-token', token_type: 'bearer', expires_at: new Date(Date.now() + 3600000).toISOString(), user: { user_id: 'U_TEST', username: 'test', role: options.hr ? 'hr' : 'employee', employee_id: options.hr ? null : 'E_TEST' } })
    }
    if (route.request().headers()['authorization'] !== 'Bearer test-session-token') return send({}, 401)
    if (path === '/auth/logout') return route.fulfill({ status: 204 })
    if (options.failFirst && !failed && path.endsWith('/trajectory')) { failed = true; return send({}, 503) }
    if (path === '/employees/E_TEST') return send({ ...profile, career_goal: options.noGoal ? null : profile.career_goal })
    if (path === '/employees/E_TEST/trajectory') return send(options.noGoal ? { ...trajectory, status: 'no_goal', target: null, requirements: [], met_count: 0, critical_gap_count: 0 } : trajectory)
    if (path === '/employees/E_TEST/history') return send(options.emptyHistory ? { items: [] } : history)
    if (path === '/skills') return send(catalog)
    if (path === '/events') return send(events)
    return send({}, 404)
  })
  return seen
}
export async function login(page: Page, password = 'test-password') {
  await page.getByLabel('Логин', { exact: true }).fill('test')
  await page.getByLabel('Пароль', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Войти в кабинет' }).click()
}

export const recommendations = {
  employee_id: 'E_TEST', as_of_date: '2026-10-01', mode: 'mock', skills_basis: 'last_review', assessed_on: '2026-09-01',
  current_skills: profile.skills, progress_pct: null, is_fallback: false, fallback_reason: null,
  message: 'Ожидаемый прирост рассчитан по правилам мероприятия.',
  items: [
    { event_id: 'EV_A', title: 'Architecture Fundamentals', format: 'online', duration_hours: 12, session_date: '2026-11-23', score: null,
      reasons: ['Подходит вашей роли.', 'Развивает критический навык API Design.'],
      skill_changes: [{ skill_id: 'SK_API', name: 'API Design', before: 2, after: 3, gain: 1 }] },
    { event_id: 'EV_B', title: 'Team Workshop', format: 'self_paced', duration_hours: 4, session_date: null, score: null,
      reasons: ['Развивает командную работу.'],
      skill_changes: [{ skill_id: 'SK_TEAM', name: 'Teamwork', before: 3, after: 4, gain: 1 }] },
  ],
}
export const simulation = {
  employee_id: 'E_TEST', event_id: 'EV_A', as_of_date: '2026-10-01', session_date: '2026-11-23',
  mode: 'mock', skills_basis: 'last_review', assessed_on: '2026-09-01', is_fallback: false, fallback_reason: null,
  message: 'Ожидаемый прирост рассчитан по правилам мероприятия.',
  skills_before: profile.skills, skills_after: { ...profile.skills, SK_API: 3 },
  progress_before_pct: null, progress_after_pct: null, skill_changes: recommendations.items[0].skill_changes,
}
