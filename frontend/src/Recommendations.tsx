import { useEffect, useRef, useState } from 'react'
import { ArrowRight, CalendarDays, Check, CircleAlert, Clock3, FlaskConical, LoaderCircle, RefreshCw, Sprout, X } from 'lucide-react'
import { api, ApiError } from './api'
import { dateLabel } from './Dashboard'
import type { CompletionResult, PreviewBasis, Recommendation, Recommendations, Simulation, SkillChange } from './types'

const formats = { online: 'Онлайн', offline: 'Очно', self_paced: 'В своём темпе' }
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function PreviewNote({ result }: { result: PreviewBasis }) {
  return <div className={`preview-note ${result.is_fallback ? 'fallback' : ''}`} role="status">
    <CircleAlert size={19} /><div><strong>{result.is_fallback ? 'Резервный расчёт' : result.mode === 'mock' ? 'Предварительный расчёт' : 'Расчёт по вашим данным'}</strong>
      {result.is_fallback && <p>{result.fallback_reason ?? 'Основной сервис временно недоступен. Используем правила каталога.'}</p>}
      <p>{result.message}</p>
      {result.skills_basis === 'current' && <p>Учтено завершённое обучение. При неизвестной дате завершения использована дата записи истории.</p>}
      {result.skills_basis === 'last_review' && <p>Основа: последняя оценка{result.assessed_on ? ` от ${dateLabel(result.assessed_on).replace(/\.$/, '')}` : ''}. Обучение после оценки ещё не учтено.</p>}
    </div>
  </div>
}

function Gains({ changes }: { changes: SkillChange[] }) {
  return changes.length ? <ul className="gain-list">{changes.map(change => <li key={change.skill_id}>
    <span>{change.name}</span><span className="gain-values"><span>{change.before}</span><ArrowRight size={13} /><strong>{change.after}</strong><span className={`gain-badge ${change.gain ? '' : 'neutral'}`}>{change.gain ? `+${change.gain}` : 'Без роста'}</span></span>
  </li>)}</ul> : <p className="muted">Прирост навыков пока не рассчитан.</p>
}

function SimulationDialog({ item, employeeId, token, onClose, onUnauthorized, asOfDate, onCompleted, idempotencyKey }: {
  item: Recommendation; employeeId: string; token: string; onClose: () => void; onUnauthorized: (message: string) => void
  asOfDate: string; onCompleted?: (result: CompletionResult) => void; idempotencyKey: string
}) {
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const inFlight = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const canComplete = item.format === 'self_paced' || item.session_date === asOfDate
  async function complete() {
    if (!confirmed || inFlight.current || !canComplete) return
    inFlight.current = true; setSaving(true); setSaveError('')
    try {
      const saved = await api<CompletionResult>(`/employees/${encodeURIComponent(employeeId)}/completions`, {
        token, method: 'POST', body: { event_id: item.event_id, session_date: item.session_date }, idempotencyKey,
      })
      if (mounted.current) onCompleted?.(saved)
    } catch (error) {
      if (!mounted.current) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
      else setSaveError(error instanceof Error ? error.message : 'Не удалось сохранить выполнение.')
    } finally { inFlight.current = false; if (mounted.current) setSaving(false) }
  }
  const dialog = useRef<HTMLDialogElement>(null)
  const [result, setResult] = useState<Simulation | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => {
      element.close(); document.body.style.overflow = overflow
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError(''); setResult(null)
    api<Simulation>(`/employees/${encodeURIComponent(employeeId)}/simulations`, {
      token, method: 'POST', body: { event_id: item.event_id, session_date: item.session_date }, signal: controller.signal,
    }).then(value => { if (!controller.signal.aborted) setResult(value) }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
      else setError(error instanceof Error ? error.message : 'Не удалось рассчитать результат.')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [item, employeeId, token, attempt, onUnauthorized])
  return <dialog ref={dialog} className="simulation-dialog" aria-labelledby="simulation-title" onCancel={event => { event.preventDefault(); if (!saving) onClose() }}>
    <div className="simulation-heading"><span className="small-icon"><FlaskConical size={23} /></span><button autoFocus className="icon-button" aria-label="Закрыть симуляцию" onClick={onClose} disabled={saving}><X size={22} /></button></div>
    <span className="eyebrow">ЕСЛИ ПРОЙТИ ЭТО ОБУЧЕНИЕ</span><h2 id="simulation-title">Симуляция результата</h2><p className="simulation-event">{item.title}</p>
    <p className="simulation-readonly">Это прогноз. Профиль и история обучения не изменяются.</p>
    {busy && <div className="loading-state simulation-loading" role="status"><LoaderCircle className="spin" size={27} /><h3>Рассчитываем изменения</h3><p>Проверяем доступность шага и прирост навыков…</p></div>}
    {error && <div className="error-banner" role="alert"><div><strong>Симуляция недоступна</strong><p>{error}</p></div><button className="button" onClick={() => setAttempt(value => value + 1)}>Повторить расчёт</button></div>}
    {result && <><PreviewNote result={result} /><div className="simulation-skills"><div className="simulation-section-title"><h3>Как изменятся навыки</h3><span>Шкала 0–5</span></div><Gains changes={result.skill_changes} /></div>
      <div className="simulation-progress"><span className="eyebrow">ГОТОВНОСТЬ К ЦЕЛИ</span>{result.progress_before_pct === null || result.progress_after_pct === null ? <p>Общий прогресс пока не рассчитан. Прогноз по отдельным навыкам показан выше.</p> : <><div className="progress-comparison"><span>{number.format(result.progress_before_pct)}%</span><ArrowRight size={22} /><strong>{number.format(result.progress_after_pct)}%</strong></div><p>Изменение: {result.progress_after_pct >= result.progress_before_pct ? '+' : ''}{number.format(result.progress_after_pct - result.progress_before_pct)} п. п.</p></>}</div></>}
    {onCompleted && result && <section className="completion-panel"><h3>Уже прошли обучение?</h3>{canComplete ? <><p>Подтвердите выполнение — запись появится в истории, навыки и рекомендации пересчитаются.</p><label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={saving} />Подтверждаю, что прошёл это обучение{item.session_date ? ` (${dateLabel(item.session_date)})` : ''}</label>{saveError && <p role="alert" className="form-error">{saveError} Если ответ потерян, повторите сохранение: повторный запрос не создаст вторую запись.</p>}<button className="button primary" onClick={complete} disabled={!confirmed || saving}>{saving ? <><LoaderCircle size={17} className="spin" />Сохраняем…</> : <><Check size={17} />Сохранить выполнение</>}</button></> : <p>Сессию можно завершить в дату её проведения: {item.session_date ? dateLabel(item.session_date) : 'дата не задана'}. Дата среза сейчас — {dateLabel(asOfDate)}.</p>}</section>}
    <button className="button simulation-close" onClick={onClose} disabled={saving}>Вернуться к рекомендациям<ArrowRight size={16} /></button>
  </dialog>
}

export function RecommendationsView({ employeeId, token, refreshKey, onUnauthorized, onCompleted }: {
  employeeId: string; token: string; refreshKey: number; onUnauthorized: (message: string) => void; onCompleted?: () => void
}) {
  const [result, setResult] = useState<Recommendations | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [success, setSuccess] = useState('')
  const keys = useRef(new Map<string, string>())
  function completionKey(item: Recommendation) {
    const key = `${employeeId}:${item.event_id}:${item.session_date ?? ''}`
    if (!keys.current.has(key)) keys.current.set(key, crypto.randomUUID())
    return keys.current.get(key)!
  }
  const [selected, setSelected] = useState<Recommendation | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError(''); setResult(null); setSelected(null)
    api<Recommendations>(`/employees/${encodeURIComponent(employeeId)}/recommendations`, { token, signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setResult(value) }).catch(error => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
        else setError(error instanceof Error ? error.message : 'Не удалось загрузить рекомендации.')
      }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [employeeId, token, refreshKey, attempt, onUnauthorized])
  return <div className="recommendations-view">
    <section className="recommendations-intro"><div><span className="eyebrow">ОТ ЦЕЛИ К ДЕЙСТВИЮ</span><h2>Ваш следующий шаг</h2><p>Выберите обучение и посмотрите, какие навыки оно поможет развить.</p></div><span className="recommendations-symbol" aria-hidden="true"><Sprout size={38} strokeWidth={1.4} /></span></section>
    {success && <div className="notice" role="status">{success}</div>}
    {busy && <div className="loading-state" role="status"><LoaderCircle className="spin" size={28} /><h3>Подбираем следующие шаги</h3><p>Проверяем профиль, историю и доступное обучение…</p></div>}
    {error && <div className="error-banner" role="alert"><div><strong>Не удалось загрузить рекомендации</strong><p>{error}</p></div><button className="button" onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} />Повторить</button></div>}
    {result && <><PreviewNote result={result} />{result.items.length ? <>
      <div className="recommendations-caption"><span>{result.mode === 'mock' ? 'Доступные варианты из каталога · без рейтинга' : 'Подобрано для вас'}</span><span>На {dateLabel(result.as_of_date)}</span></div>
      <div className="recommendation-grid">{result.items.slice(0, 3).map((item, index) => <article className="recommendation-card card" key={`${item.event_id}:${item.session_date ?? ''}`}>
        <div className="recommendation-top"><span className="recommendation-number">ШАГ {String(index + 1).padStart(2, '0')}</span><span className="pill neutral">{formats[item.format]}</span></div>
        <h3>{item.title}</h3><div className="recommendation-meta"><span><Clock3 size={16} />{number.format(item.duration_hours)} ч</span><span><CalendarDays size={16} />{item.session_date ? dateLabel(item.session_date) : item.format === 'self_paced' ? 'В любое время' : 'Дата уточняется'}</span></div>
        {item.why_this ? <div className="recommendation-reasons"><h4>WHY THIS</h4><p>{item.why_this}</p></div> :
        <div className="recommendation-reasons"><h4>Почему этот шаг</h4><ul>{item.reasons.map((reason, i) => <li key={i}><Check size={15} /><span>{reason}</span></li>)}</ul></div>}
        {item.why_not && <div className="recommendation-reasons"><h4>WHY NOT</h4><p>{item.why_not}</p></div>}
        {item.readiness_before != null && item.readiness_after != null && <div className="simulation-progress"><h4>Readiness</h4><div className="progress-comparison"><span>{number.format(item.readiness_before)}%</span><ArrowRight size={20} /><strong>{number.format(item.readiness_after)}%</strong></div><p>+{number.format(item.readiness_after - item.readiness_before)} pp</p></div>}
        {item.expected_career_impact && <p>{item.expected_career_impact}</p>}
        {item.caution && <p className="muted">{item.caution}</p>}
        <div className="recommendation-gains"><h4>Ожидаемый прирост навыков</h4><Gains changes={item.skill_changes} /></div>
        <button className="button primary" onClick={() => setSelected(item)} aria-label={`Симулировать: ${item.title}`}><FlaskConical size={17} />Посмотреть результат<ArrowRight size={16} /></button>
      </article>)}</div><div className="basis-note"><FlaskConical size={17} /><p>Каждый шаг рассчитывается отдельно. Симуляция показывает возможный результат обучения, а не подтверждённый новый уровень.</p></div>
    </> : <section className="card empty-state"><span className="small-icon"><Sprout size={28} /></span><h3>Подходящих шагов пока нет</h3><p>В текущем каталоге нет доступного обучения с приростом навыков с учётом роли, грейда, требований, дат и пройденных мероприятий. Обсудите другие варианты с HR или обновите список позже.</p><button className="button" onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} />Обновить рекомендации</button></section>}</>}
    {selected && <SimulationDialog item={selected} employeeId={employeeId} token={token} onClose={() => setSelected(null)} onUnauthorized={onUnauthorized} asOfDate={result!.as_of_date} idempotencyKey={completionKey(selected)} onCompleted={onCompleted ? saved => { setSelected(null); setSuccess(saved.replayed ? 'Выполнение уже сохранено. Данные обновляются.' : 'Выполнение сохранено. Обновляем навыки, историю и рекомендации.'); onCompleted() } : undefined} />}
  </div>
}
