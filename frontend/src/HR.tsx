import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, CircleAlert, FileUp, LoaderCircle, LogOut, RefreshCw, Search, ShieldCheck, Users } from 'lucide-react'
import { api, ApiError, loadDashboard, type ImportIssue } from './api'
import { dateLabel, HistoryView, SkillsView } from './Dashboard'
import { RecommendationsView } from './Recommendations'
import type { DashboardData, HROverview, ImportResult, Session } from './types'

const statuses = { available: 'Есть шаг', none: 'Нет подходящего шага', unavailable: 'Расчёт недоступен' }

function ImportView({ token, onUnauthorized, onImported, openProfile }: {
  token: string; onUnauthorized: (message: string) => void; onImported: () => void; openProfile: (id: string) => void
}) {
  const [employees, setEmployees] = useState<File | null>(null)
  const [history, setHistory] = useState<File | null>(null)
  const [payload, setPayload] = useState<{ employees_json?: string; history_csv?: string } | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [issues, setIssues] = useState<ImportIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  function reset() { setResult(null); setPayload(null); setError(''); setIssues([]) }
  async function submit(save: boolean) {
    if (busy) return
    setBusy(true); setError(''); setIssues([])
    try {
      if ([employees, history].some(file => file && file.size > 2_000_000)) throw new Error('Размер каждого файла — не больше 2 МБ.')
      const body = save && payload ? payload : {
        ...(employees ? { employees_json: await employees.text() } : {}),
        ...(history ? { history_csv: await history.text() } : {}),
      }
      const response = await api<ImportResult>('/hr/imports', { token, method: 'POST', body: { ...body, dry_run: !save } })
      setPayload(body); setResult(response)
      if (save) onImported()
    } catch (error) {
      setResult(null)
      if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
      else { setError(error instanceof Error ? error.message + (error instanceof ApiError && error.status === 0 ? ' Повторите проверку: уже сохранённые записи будут пропущены.' : '') : 'Не удалось загрузить файлы.'); if (error instanceof ApiError) setIssues(error.issues) }
    } finally { setBusy(false) }
  }
  return <section className="card import-card"><div className="section-heading"><div><span className="eyebrow">НОВЫЕ ДАННЫЕ</span><h2>Импорт профилей жюри</h2></div><span className="small-icon"><FileUp size={23} /></span></div>
    <div className="import-body"><p>Добавьте профили в JSON и, при необходимости, историю в CSV. Сначала проверьте файлы, затем сохраните весь пакет. Новые сотрудники сразу появятся в HR-обзоре и расчётах.</p>
      <div className="import-rules"><CircleAlert size={19} /><p>Существующие записи не перезаписываются. Точные повторы пропускаются; конфликтующие ID и повторные завершения отклоняются. При любой ошибке пакет не сохраняется.</p></div>
      <div className="upload-grid"><label className="upload-box"><strong>Профили · JSON</strong><span>Массив профилей или объект с полем employees · до 500 профилей</span><input aria-label="Файл профилей JSON" type="file" accept=".json,application/json" disabled={busy} onChange={event => { setEmployees(event.target.files?.[0] ?? null); reset() }} /><a href="/templates/employees.json" download>Скачать пример JSON</a></label>
        <label className="upload-box"><strong>История · CSV</strong><span>UTF-8, разделитель — запятая · до 10 000 записей</span><input aria-label="Файл истории CSV" type="file" accept=".csv,text/csv" disabled={busy} onChange={event => { setHistory(event.target.files?.[0] ?? null); reset() }} /><a href="/templates/history.csv" download>Скачать шаблон CSV</a></label></div>
      <p className="muted">Можно загрузить один файл или оба. Размер каждого — до 2 МБ. Для входа нового сотрудника администратор отдельно создаёт учётную запись.</p>
      {error && <div className="error-banner" role="alert"><div><strong>Не удалось подтвердить импорт</strong><p>{error}</p></div></div>}
      {issues.length > 0 && <div className="table-scroll"><table className="requirements-table"><caption>Ошибки проверки · первые 100</caption><thead><tr><th>Файл / строка</th><th>Поле</th><th>Что исправить</th></tr></thead><tbody>{issues.map((issue, index) => <tr key={index}><td>{issue.file}{issue.row ? ` · ${issue.row}` : ''}</td><td>{issue.field || '—'}</td><td>{issue.message}</td></tr>)}</tbody></table></div>}
      {busy && <p className="import-busy" role="status"><LoaderCircle className="spin" size={19} />Проверяем и обрабатываем данные…</p>}
      {result && <div className="import-result" role="status"><h3>{result.dry_run ? 'Файлы проверены. Готово к сохранению' : 'Импорт сохранён'}</h3><p>{result.dry_run ? 'Будет добавлено' : 'Добавлено'}: профилей — {result.employees_added}, записей истории — {result.history_added}.</p><p>Пропущено точных повторов: профилей — {result.employees_skipped}, записей — {result.history_skipped}.</p>{!result.dry_run && result.employee_ids.length > 0 && <button className="text-button" onClick={() => openProfile(result.employee_ids[0])}>Открыть импортированный профиль<ArrowRight size={16} /></button>}</div>}
      <div className="import-actions"><button className="button" onClick={() => submit(false)} disabled={busy || (!employees && !history)}><ShieldCheck size={17} />Проверить файлы</button>{result?.dry_run && <button className="button primary" onClick={() => submit(true)} disabled={busy}><FileUp size={17} />Сохранить импорт</button>}</div>
    </div>
  </section>
}

function HRProfile({ id, token, onBack, onUnauthorized }: { id: string; token: string; onBack: () => void; onUnauthorized: (message: string) => void }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [tab, setTab] = useState<'skills' | 'history' | 'recommendations'>('skills')
  useEffect(() => {
    const controller = new AbortController()
    setError(''); setData(null)
    loadDashboard(id, token, controller.signal).then(value => { if (!controller.signal.aborted) setData(value) }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
      else setError(error instanceof Error ? error.message : 'Не удалось открыть профиль.')
    })
    return () => controller.abort()
  }, [id, token, revision, onUnauthorized])
  return <><button className="text-button" onClick={onBack}><ArrowLeft size={17} />К HR-обзору</button>{error ? <div className="error-banner" role="alert"><p>{error}</p><button className="button" onClick={() => setRevision(value => value + 1)}>Повторить</button></div> : !data ? <div className="loading-state" role="status"><LoaderCircle className="spin" />Загружаем профиль…</div> : <><div className="page-heading"><div><span className="eyebrow">ПРОСМОТР HR · {id}</span><h1>{data.profile.full_name}</h1><p>{data.profile.department} · {data.profile.role} · {data.profile.grade}</p></div></div><div className="hr-tabs">{(['skills', 'history', 'recommendations'] as const).map(value => <button className={`button ${tab === value ? 'primary' : ''}`} aria-pressed={tab === value} key={value} onClick={() => setTab(value)}>{value === 'skills' ? 'Навыки и требования' : value === 'history' ? 'История обучения' : 'Рекомендации'}</button>)}</div>{tab === 'skills' && <SkillsView data={data} />}{tab === 'history' && <HistoryView data={data} />}{tab === 'recommendations' && <RecommendationsView employeeId={id} token={token} refreshKey={revision} onUnauthorized={onUnauthorized} />}</>}</>
}

export function HRWorkspace({ session, onLogout, loggingOut, onUnauthorized }: {
  session: Session; onLogout: () => void; loggingOut: boolean; onUnauthorized: (message: string) => void
}) {
  const [data, setData] = useState<HROverview | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [tab, setTab] = useState<'overview' | 'employees' | 'events' | 'import'>('overview')
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [onlyNoStep, setOnlyNoStep] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    api<HROverview>('/hr/overview', { token: session.access_token, signal: controller.signal }).then(value => { if (!controller.signal.aborted) setData(value) }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized(error.message)
      else setError(error instanceof Error ? error.message : 'Не удалось загрузить HR-обзор.')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [session.access_token, revision, onUnauthorized])
  const employees = data?.employees.filter(employee => (!onlyNoStep || employee.recommendation_status === 'none') && `${employee.full_name} ${employee.employee_id} ${employee.department} ${employee.role}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())) ?? []
  return <div className="hr-shell"><header className="hr-header"><div className="hr-brand"><span className="small-icon"><Users size={23} /></span><strong>careerquest<span>.</span></strong><span className="pill">HR</span></div><div><span className="hr-account">{session.user.username}</span><button className="button" aria-label="Выйти" disabled={loggingOut} onClick={onLogout}><LogOut size={16} />Выйти</button></div></header><main className="hr-main">
    {selected ? <HRProfile key={selected} id={selected} token={session.access_token} onBack={() => setSelected(null)} onUnauthorized={onUnauthorized} /> : <><div className="page-heading"><div><span className="eyebrow">РАЗВИТИЕ КОМАНДЫ</span><h1>HR-обзор</h1><p>Дефициты навыков, доступные шаги и участие в обучении.</p></div><button className="button" aria-label="Обновить HR-данные" disabled={busy} onClick={() => setRevision(value => value + 1)}><RefreshCw size={16} className={busy ? 'spin' : ''} />Обновить</button></div>
      <nav className="hr-tabs" aria-label="Разделы HR">{([{ id: 'overview', label: 'Обзор' }, { id: 'employees', label: 'Сотрудники' }, { id: 'events', label: 'Мероприятия' }, { id: 'import', label: 'Импорт JSON/CSV' }] as const).map(item => <button key={item.id} aria-current={tab === item.id ? 'page' : undefined} className={`button ${tab === item.id ? 'primary' : ''}`} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
      {error && <div className="error-banner" role="alert"><div><strong>Не удалось обновить HR-данные</strong><p>{error}{data ? ' Показана последняя успешная загрузка.' : ''}</p></div><button className="button" disabled={busy} onClick={() => setRevision(value => value + 1)}>Повторить</button></div>}
      {tab === 'import' ? <ImportView token={session.access_token} onUnauthorized={onUnauthorized} onImported={() => setRevision(value => value + 1)} openProfile={setSelected} /> : !data && busy ? <div className="loading-state" role="status"><LoaderCircle size={28} className="spin" /><h2>Собираем данные команды</h2></div> : data && <>
        {tab === 'overview' && <><div className="hr-stats"><div className="card"><span>Сотрудников</span><strong>{data.employees.length}</strong><p>в текущей базе</p></div><div className="card"><span>Без подходящего шага</span><strong>{data.no_step_count}</strong><button className="text-button" onClick={() => { setOnlyNoStep(true); setTab('employees') }}>Посмотреть сотрудников<ArrowRight size={15} /></button></div><div className="card"><span>Завершений обучения</span><strong>{data.events.reduce((sum, event) => sum + event.completed, 0)}</strong><p>записей, включая повторные сессии</p></div></div>
          {data.unavailable_count > 0 && <div className="notice" role="status">Для {data.unavailable_count} сотрудников расчёт недоступен. Они не включены в число сотрудников без подходящего шага.</div>}
          <section className="card"><div className="section-heading"><div><span className="eyebrow">ГДЕ НУЖНО РАЗВИТИЕ</span><h2>Частые дефициты навыков</h2></div></div>{data.skill_gaps.length ? <div className="hr-gap-list">{data.skill_gaps.map(skill => <div className="hr-gap-row" key={skill.skill_id}><div><strong>{skill.name}</strong><span>Критический дефицит у {skill.critical_count}</span></div><div className="hr-gap-bar" aria-hidden="true"><span style={{ width: `${skill.employees_count / Math.max(1, data.employees.length) * 100}%` }} /></div><span>{skill.employees_count} чел.</span></div>)}</div> : <div className="empty-state"><h3>Дефицитов по заданным целям нет</h3><p>Сотрудники без цели не участвуют в этом сравнении.</p></div>}</section></>}
        {tab === 'employees' && <section className="card"><div className="section-heading"><h2>Сотрудники</h2><span className="pill neutral">{employees.length}</span></div><div className="filter-toolbar"><label className="search-field"><Search size={17} /><input aria-label="Поиск сотрудников" placeholder="Имя, ID, отдел или роль…" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="hr-checkbox"><input type="checkbox" checked={onlyNoStep} onChange={event => setOnlyNoStep(event.target.checked)} />Только без подходящего шага</label></div><div className="table-scroll"><table className="requirements-table"><caption className="sr-only">Сотрудники и доступность рекомендаций</caption><thead><tr><th>Сотрудник</th><th>Отдел / роль</th><th>Рекомендации</th><th>Критические дефициты</th><th /></tr></thead><tbody>{employees.map(employee => <tr key={employee.employee_id}><td><strong>{employee.full_name}</strong><small>{employee.employee_id}</small></td><td>{employee.department}<small>{employee.role} · {employee.grade}</small></td><td><span className="pill neutral">{statuses[employee.recommendation_status]}</span>{employee.recommendation_status !== 'available' && <small className="hr-reason">{employee.reason}</small>}</td><td>{employee.critical_gap_count ?? '—'}</td><td><button className="text-button" aria-label={`Открыть профиль ${employee.full_name}`} onClick={() => setSelected(employee.employee_id)}>Открыть<ArrowRight size={15} /></button></td></tr>)}</tbody></table></div>{!employees.length && <div className="empty-state"><h3>Сотрудники не найдены</h3><p>Измените фильтр или добавьте профили через импорт.</p></div>}</section>}
        {tab === 'events' && <section className="card"><div className="section-heading"><div><span className="eyebrow">УЧАСТИЕ И РЕЗУЛЬТАТЫ</span><h2>Обучение по мероприятиям</h2></div></div><div className="table-scroll"><table className="requirements-table"><caption className="sr-only">Участие и завершения по мероприятиям</caption><thead><tr><th>Мероприятие</th><th>Участников</th><th>Записей</th><th>Завершено</th><th>В процессе</th><th>Другие статусы</th></tr></thead><tbody>{data.events.map(event => <tr key={event.event_id}><td><strong>{event.title}</strong><small>{event.event_id}</small></td><td>{event.participants}</td><td>{event.records}</td><td>{event.completed}</td><td>{event.in_progress}</td><td>{event.other}</td></tr>)}</tbody></table></div><div className="card-footnote">Участники — уникальные сотрудники. Записи и завершения учитывают каждую сессию, включая повторяемый клуб. Другие статусы: пропуск, отказ, прекращение и просрочка.</div></section>}
        <div className="basis-note"><CircleAlert size={16} /><p>{data.message} Срез: {dateLabel(data.as_of_date)}{data.mode === 'mock' ? ' Используется предварительный расчёт по каталогу и истории.' : ''}</p></div>
      </>}
    </>}
  </main></div>
}
