import type { Catalog, DashboardData, Employee, HistoryRecord, Activity, Trajectory } from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, options: {
  token?: string; method?: string; body?: unknown; signal?: AbortSignal
} = {}): Promise<T> {
  const timeout = AbortSignal.timeout(15000)
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      method: options.method ?? 'GET', signal,
      headers: {
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: 'no-store',
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(0, 'Сервер не ответил. Проверьте подключение и попробуйте ещё раз.')
  }
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: path === '/auth/login' ? 'Неверный логин или пароль.' : 'Сессия завершена. Войдите снова.',
      403: 'У этой учётной записи нет доступа к данным.',
      404: 'Профиль или данные не найдены. Обратитесь к администратору.',
      422: 'Проверьте введённые данные.',
      429: 'Слишком много попыток входа. Повторите через 5 минут.',
      503: 'Данные временно недоступны. Попробуйте чуть позже.',
    }
    throw new ApiError(response.status, messages[response.status] ?? 'Не удалось загрузить данные. Попробуйте ещё раз.')
  }
  return body as T
}

export async function loadDashboard(employeeId: string, token: string, signal: AbortSignal): Promise<DashboardData> {
  const base = `/employees/${encodeURIComponent(employeeId)}`
  const options = { token, signal }
  const [profile, catalog, history, events, trajectory] = await Promise.all([
    api<Employee>(base, options), api<Catalog>('/skills', options),
    api<{ items: HistoryRecord[] }>(`${base}/history`, options),
    api<{ items: Activity[] }>('/events', options), api<Trajectory>(`${base}/trajectory`, options),
  ])
  return { profile, catalog, history: history.items, events: events.items, trajectory }
}
