import { test, expect } from '@playwright/test'
import { login, mockApi, profile, recommendations, simulation, trajectory } from './fixtures'

const hr = {
  as_of_date: '2026-10-01', mode: 'mock', no_step_count: 1, unavailable_count: 1, message: 'Сводка по заданным целям.',
  employees: [
    { employee_id: 'E_TEST', full_name: 'Alex Test', department: 'Engineering', role: 'Backend Engineer', grade: 'Junior', recommendation_status: 'available', reason: '', critical_gap_count: 1 },
    { employee_id: 'E_EMPTY', full_name: 'Sam Empty', department: 'Research', role: 'Analyst', grade: 'Lead', recommendation_status: 'none', reason: 'Нет подходящего обучения в каталоге.', critical_gap_count: 0 },
    { employee_id: 'E_ERROR', full_name: 'Robin Error', department: 'Research', role: 'Analyst', grade: 'Senior', recommendation_status: 'unavailable', reason: 'Расчёт недоступен.', critical_gap_count: null },
  ],
  skill_gaps: [{ skill_id: 'SK_API', name: 'API Design', employees_count: 1, critical_count: 1 }],
  events: [{ event_id: 'EV_036', title: 'Speaking Club', participants: 1, records: 3, completed: 2, in_progress: 1, other: 0 }],
}

test('completion retries with same key then refreshes skills and recommendations', async ({ page }) => {
  await mockApi(page)
  let saved = false
  const course = recommendations.items[1]
  await page.route('**/recommendations', route => route.fulfill({ json: { ...recommendations, items: saved ? [] : [course] } }))
  await page.route('**/simulations', route => route.fulfill({ json: { ...simulation, event_id: course.event_id, session_date: null, skill_changes: course.skill_changes } }))
  await page.route('**/trajectory', route => route.fulfill({ json: {
    ...trajectory, skills_basis: 'current', current_skills: { ...profile.skills, SK_TEAM: saved ? 4 : 3 },
    requirements: trajectory.requirements.map(row => row.skill_id === 'SK_TEAM' ? { ...row, current_level: saved ? 4 : 3 } : row),
  } }))
  const keys: string[] = []
  await page.route('**/completions', route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON()).toEqual({ event_id: 'EV_B', session_date: null })
    keys.push(route.request().headers()['idempotency-key'])
    if (keys.length === 1) return route.abort('failed')
    saved = true
    return route.fulfill({ json: { replayed: true, completion: { completion_id: 'C_TEST', event_id: 'EV_B', session_date: null, result: simulation } } })
  })
  await page.goto('/'); await login(page)
  await page.getByRole('button', { name: 'К рекомендациям', exact: true }).click()
  await page.getByRole('button', { name: 'Симулировать: Team Workshop' }).click()
  const dialog = page.getByRole('dialog')
  const save = dialog.getByRole('button', { name: 'Сохранить выполнение' })
  await expect(save).toBeDisabled()
  await dialog.getByRole('checkbox').check()
  await save.click()
  await expect(dialog.getByRole('alert')).toContainText('повторный запрос не создаст вторую запись')
  await save.click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Выполнение уже сохранено. Данные обновляются.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Подходящих шагов пока нет' })).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBeTruthy(); expect(keys[1]).toBe(keys[0])
  await page.getByRole('button', { name: 'Мои навыки', exact: true }).click()
  await expect(page.locator('.skill-card').filter({ has: page.getByRole('heading', { name: 'Teamwork', exact: true }) }).locator('.skill-level-caption')).toContainText('4 / 5')
})

test('future scheduled session cannot be marked completed', async ({ page }) => {
  await mockApi(page)
  await page.route('**/recommendations', route => route.fulfill({ json: recommendations }))
  await page.route('**/simulations', route => route.fulfill({ json: simulation }))
  await page.goto('/'); await login(page)
  await page.getByRole('button', { name: 'К рекомендациям', exact: true }).click()
  await page.getByRole('button', { name: 'Симулировать: Architecture Fundamentals' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Сессию можно завершить в дату её проведения')
  await expect(dialog.getByRole('button', { name: 'Сохранить выполнение' })).toHaveCount(0)
})

test('HR aggregates, no-step filter, event counts and read-only profile', async ({ page }) => {
  await mockApi(page, { hr: true })
  await page.route('**/hr/overview', route => route.fulfill({ json: hr }))
  await page.route('**/recommendations', route => route.fulfill({ json: recommendations }))
  await page.route('**/simulations', route => route.fulfill({ json: simulation }))
  await page.goto('/'); await login(page)
  await expect(page.getByRole('heading', { name: 'Частые дефициты навыков' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('не включены в число сотрудников без подходящего шага')
  await page.getByRole('button', { name: 'Посмотреть сотрудников' }).click()
  await expect(page.getByRole('cell', { name: 'Sam Empty E_EMPTY' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Robin Error E_ERROR' })).toHaveCount(0)
  await page.getByRole('checkbox').uncheck()
  await page.getByLabel('Поиск сотрудников').fill('Alex')
  await page.getByRole('button', { name: 'Открыть профиль Alex Test' }).click()
  await expect(page.getByRole('heading', { name: 'Alex Test' })).toBeVisible()
  await page.getByRole('button', { name: 'Рекомендации', exact: true }).click()
  await page.getByRole('button', { name: 'Симулировать: Team Workshop' }).click()
  await expect(page.getByRole('dialog').locator('.gain-list')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Сохранить выполнение' })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'К HR-обзору' }).click()
  await page.getByRole('button', { name: 'Мероприятия', exact: true }).click()
  const row = page.getByRole('row').filter({ hasText: 'Speaking Club' })
  await expect(row.getByRole('cell')).toHaveText(['Speaking ClubEV_036', '1', '3', '2', '1', '0'])
})

test('HR import checks files before save, shows row errors, refreshes aggregates and works on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, { hr: true })
  let loads = 0
  await page.route('**/hr/overview', route => { loads++; return route.fulfill({ json: hr }) })
  let invalid = true
  const requests: { dry_run: boolean; employees_json: string }[] = []
  await page.route('**/hr/imports', route => {
    const body = route.request().postDataJSON(); requests.push(body)
    return route.fulfill(invalid ? { status: 422, json: { detail: { code: 'invalid_import', message: 'Исправьте указанные ошибки.', issues: [{ file: 'employees.json', row: 1, field: 'skills.SK_API', message: 'Уровень должен быть 0–5.' }] } } } : { json: {
      dry_run: body.dry_run, employees_added: 1, employees_skipped: 0, history_added: 0, history_skipped: 0, employee_ids: ['E_TEST'],
    } })
  })
  await page.goto('/'); await login(page)
  await page.getByRole('button', { name: 'Импорт JSON/CSV' }).click()
  await expect(page.getByRole('button', { name: 'Сохранить импорт' })).toHaveCount(0)
  await page.getByLabel('Файл профилей JSON').setInputFiles({ name: 'employees.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify([profile])) })
  await page.getByRole('button', { name: 'Проверить файлы' }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось подтвердить импорт')
  await expect(page.getByRole('cell', { name: 'skills.SK_API' })).toBeVisible()
  invalid = false
  await page.getByRole('button', { name: 'Проверить файлы' }).click()
  await expect(page.getByRole('heading', { name: 'Файлы проверены. Готово к сохранению' })).toBeVisible()
  const beforeLoads = loads
  await page.getByRole('button', { name: 'Сохранить импорт' }).click()
  await expect(page.getByRole('heading', { name: 'Импорт сохранён' })).toBeVisible()
  await expect.poll(() => loads).toBeGreaterThan(beforeLoads)
  expect(requests.map(body => body.dry_run)).toEqual([true, true, false])
  expect(requests[2].employees_json).toBe(requests[1].employees_json)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Открыть импортированный профиль' }).click()
  await expect(page.getByRole('heading', { name: 'Alex Test' })).toBeVisible()
})
