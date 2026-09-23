import { test, expect, type Page } from '@playwright/test'
import { login, mockApi, recommendations, simulation } from './fixtures'

async function openRecommendations(page: Page) {
  await page.goto('/'); await login(page)
  await page.getByRole('button', { name: 'К рекомендациям', exact: true }).click()
}

test('cards, loading, simulation request, no writes, and keyboard focus', async ({ page }) => {
  const seen = await mockApi(page)
  let release: () => void = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/recommendations', async route => { await gate; await route.fulfill({ json: recommendations }) })
  let releaseSimulation: () => void = () => {}
  const simulationGate = new Promise<void>(resolve => { releaseSimulation = resolve })
  const bodies: unknown[] = []
  await page.route('**/simulations', async route => {
    expect(route.request().headers().authorization).toBe('Bearer test-session-token')
    bodies.push(route.request().postDataJSON()); await simulationGate
    await route.fulfill({ json: simulation })
  })
  await openRecommendations(page)
  await expect(page.getByRole('status')).toContainText('Подбираем следующие шаги')
  release()
  await expect(page.getByRole('article')).toHaveCount(2)
  const first = page.getByRole('article').first()
  await expect(first).toContainText('Онлайн')
  await expect(first).toContainText('12 ч')
  await expect(first).toContainText('23 ноября 2026')
  await expect(first).toContainText('Развивает критический навык API Design')
  await expect(first.locator('.gain-values')).toHaveText('23+1')
  await expect(page.getByRole('article').nth(1)).toContainText('В любое время')
  const trigger = first.getByRole('button', { name: 'Симулировать: Architecture Fundamentals' })
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('status')).toContainText('Рассчитываем изменения')
  await expect(dialog).toContainText('Профиль и история обучения не изменяются')
  releaseSimulation()
  await expect(dialog.locator('.gain-values')).toHaveText('23+1')
  await expect(dialog).toContainText('Общий прогресс пока не рассчитан')
  expect(bodies.length).toBeGreaterThan(0)
  expect(bodies.every(body => JSON.stringify(body) === JSON.stringify({ event_id: 'EV_A', session_date: '2026-11-23' }))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await page.getByRole('button', { name: 'Симулировать: Team Workshop' }).click()
  await expect.poll(() => bodies.some(body => JSON.stringify(body) === JSON.stringify({ event_id: 'EV_B', session_date: null }))).toBe(true)
  expect(seen.some(path => path.endsWith('/completions'))).toBe(false)
})

test('recommendation retry, fallback, empty result, and refresh', async ({ page }) => {
  await mockApi(page)
  let phase: 'error' | 'empty' | 'cards' = 'error'
  await page.route('**/recommendations', route => {
    return route.fulfill(phase === 'error' ? { status: 503, json: {} } : { json: {
      ...recommendations, is_fallback: true, fallback_reason: 'Основной сервис временно недоступен.',
      items: phase === 'empty' ? [] : recommendations.items,
    } })
  })
  await openRecommendations(page)
  await expect(page.getByRole('alert')).toContainText('Не удалось загрузить рекомендации')
  await expect(page.getByRole('article')).toHaveCount(0)
  phase = 'empty'
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Резервный расчёт')
  await expect(page.getByRole('heading', { name: 'Подходящих шагов пока нет' })).toBeVisible()
  phase = 'cards'
  await page.getByRole('button', { name: 'Обновить рекомендации', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByRole('heading', { name: 'Подходящих шагов пока нет' })).toHaveCount(0)
})

test('simulation failure and fallback retry preserve zero progress', async ({ page }) => {
  await mockApi(page)
  await page.route('**/recommendations', route => route.fulfill({ json: recommendations }))
  let unavailable = true
  await page.route('**/simulations', route => route.fulfill(unavailable ? { status: 409, json: {} } : { json: {
    ...simulation, is_fallback: true, fallback_reason: 'Показан резервный расчёт.', progress_before_pct: 0, progress_after_pct: 12.5,
  } }))
  await openRecommendations(page)
  await page.getByRole('button', { name: 'Симулировать: Architecture Fundamentals' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('alert')).toContainText('Этот шаг больше недоступен')
  await expect(dialog.locator('.gain-list')).toHaveCount(0)
  unavailable = false
  await dialog.getByRole('button', { name: 'Повторить расчёт' }).click()
  await expect(dialog.getByRole('status')).toContainText('Резервный расчёт')
  await expect(dialog.locator('.progress-comparison')).toHaveText('0%12,5%')
  await expect(dialog).toContainText('Изменение: +12,5 п. п.')
  await expect(dialog.getByRole('alert')).toHaveCount(0)
})

test('forbidden recommendations are not fabricated, expired simulation clears session', async ({ page }) => {
  await mockApi(page)
  let forbidden = true
  await page.route('**/recommendations', route => route.fulfill(forbidden ? { status: 403, json: {} } : { json: recommendations }))
  await page.route('**/simulations', route => route.fulfill({ status: 401, json: {} }))
  await openRecommendations(page)
  await expect(page.getByRole('alert')).toContainText('нет доступа')
  await expect(page.getByRole('article')).toHaveCount(0)
  forbidden = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await page.getByRole('button', { name: 'Симулировать: Architecture Fundamentals' }).click()
  await expect(page.getByRole('heading', { name: 'Рады видеть вас' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('Сессия завершена')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('closing pending simulation ignores late response and supports mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  await page.route('**/recommendations', route => route.fulfill({ json: recommendations }))
  let release: () => void = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/simulations', async route => {
    const body = route.request().postDataJSON()
    if (body.event_id === 'EV_A') await gate
    await route.fulfill({ json: { ...simulation, event_id: body.event_id,
      skill_changes: body.event_id === 'EV_A' ? simulation.skill_changes : recommendations.items[1].skill_changes,
    } })
  })
  await openRecommendations(page)
  await page.getByRole('button', { name: 'Симулировать: Architecture Fundamentals' }).click()
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('Рассчитываем изменения')
  await page.getByRole('button', { name: 'Закрыть симуляцию' }).click()
  await page.getByRole('button', { name: 'Симулировать: Team Workshop' }).click()
  release()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.gain-list')).toContainText('Teamwork')
  await expect(dialog.locator('.gain-list')).not.toContainText('API Design')
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await dialog.getByRole('button', { name: 'Вернуться к рекомендациям' }).click()
  await expect(dialog).toHaveCount(0)
})
