import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, ArrowUpRight, BookOpen, Compass, Eye, EyeOff, History, Layers3, LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, Menu, RefreshCw, Route, ShieldCheck, X } from 'lucide-react'
import { api, ApiError, loadDashboard } from './api'
import type { DashboardData, Session } from './types'
import { HistoryView, Overview, SkillsView, TrajectoryView, dateLabel, initials } from './Dashboard'

export type Tab = 'overview' | 'skills' | 'history' | 'trajectory'
const tabs = [
  { id: 'overview', label: 'Моё развитие', icon: LayoutDashboard },
  { id: 'skills', label: 'Мои навыки', icon: Layers3 },
  { id: 'history', label: 'История обучения', icon: History },
  { id: 'trajectory', label: 'Моя траектория', icon: Route },
] as const

function Brand() {
  return <div className="brand"><span className="brand-icon"><Compass size={25} strokeWidth={1.8} /></span><span>career<span className="brand-quest">quest<span className="brand-dot">.</span></span></span></div>
}

function Login({ onLogin, notice }: { onLogin: (session: Session) => void; notice: string }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true)
    try { onLogin(await api<Session>('/auth/login', { method: 'POST', body: { username: username.trim(), password } })) }
    catch (error) { setError(error instanceof Error ? error.message : 'Не удалось войти.') }
    finally { setBusy(false) }
  }
  return <div className="login-page">
    <section className="login-story"><Brand /><div className="login-story-content"><span className="eyebrow light">ВАШЕ РАЗВИТИЕ. ВАШ МАРШРУТ.</span><h1>Следующий шаг<br />начинается<br /><em>с вас.</em></h1><p>Узнайте свои сильные стороны, определите цель и двигайтесь к ней в своём темпе.</p><div className="login-steps"><span><Layers3 size={18} />Навыки</span><i /><span><Route size={18} />Траектория</span><i /><span><Compass size={18} />Новая роль</span></div></div><div className="login-note">Career Quest <span>Развитие с понятной целью</span></div></section>
    <main className="login-panel"><div className="login-mobile-brand"><Brand /></div><div className="login-form-wrap"><span className="small-icon"><LockKeyhole size={22} /></span><span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span><h2>Рады видеть вас</h2><p className="muted">Войдите, чтобы продолжить свой путь развития.</p>
      {notice && <div className="notice" role="status">{notice}</div>}
      <form onSubmit={submit}>
        <label htmlFor="username">Логин</label><input id="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={64} value={username} onChange={e => setUsername(e.target.value)} placeholder="Ваш логин" disabled={busy} />
        <label htmlFor="password">Пароль</label><div className="password-field"><input id="password" type={visible ? 'text' : 'password'} autoComplete="current-password" required maxLength={256} value={password} onChange={e => setPassword(e.target.value)} placeholder="Введите пароль" disabled={busy} /><button type="button" className="icon-button" aria-label={visible ? 'Скрыть пароль' : 'Показать пароль'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="button primary login-submit" disabled={busy || !username.trim() || !password}>{busy ? <><LoaderCircle className="spin" size={18} />Входим…</> : <>Войти в кабинет<ArrowRight size={18} /></>}</button>
      </form><p className="login-help">Нет данных для входа?<br />Обратитесь к администратору вашей команды.</p><div className="secure-note"><ShieldCheck size={17} />Доступ к личным данным защищён</div></div><span className="login-footer">Маленькие шаги. Большие возможности.</span></main>
  </div>
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<Tab>('overview')
  const [mobileMenu, setMobileMenu] = useState(false)
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const clearSession = useCallback((message = '') => {
    setSession(null); setData(null); setError(''); setNotice(message); setTab('overview'); setMobileMenu(false)
  }, [])
  useEffect(() => {
    if (!session) return
    const remaining = Date.parse(session.expires_at) - Date.now()
    const timeout = window.setTimeout(() => clearSession('Сессия завершена. Войдите снова.'), Math.max(0, remaining))
    return () => window.clearTimeout(timeout)
  }, [session, clearSession])
  useEffect(() => {
    if (!session?.user.employee_id) return
    const controller = new AbortController()
    setBusy(true); setError('')
    loadDashboard(session.user.employee_id, session.access_token, controller.signal)
      .then(result => { if (!controller.signal.aborted) setData(result) })
      .catch(error => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) clearSession(error.message)
        else setError(error instanceof Error ? error.message : 'Не удалось загрузить кабинет.')
      }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [session, revision, clearSession])
  useEffect(() => { document.title = `${tabs.find(item => item.id === tab)?.label} · Career Quest` }, [tab])
  async function logout() {
    if (!session) return
    setLoggingOut(true)
    let message = ''
    try { await api('/auth/logout', { method: 'POST', token: session.access_token }) }
    catch (error) { if (!(error instanceof ApiError && error.status === 401)) message = 'Вы вышли на этом устройстве. Сервер не ответил на запрос завершения сессии.' }
    finally { clearSession(message); setLoggingOut(false) }
  }
  function navigate(next: Tab) { setTab(next); setMobileMenu(false); window.scrollTo({ top: 0, behavior: 'instant' }) }
  if (!session) return <Login notice={notice} onLogin={value => { setSession(value); setNotice('') }} />
  const profile = data?.profile
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    {mobileMenu && <button className="menu-backdrop" aria-label="Закрыть меню" onClick={() => setMobileMenu(false)} />}
    <aside className={`sidebar ${mobileMenu ? 'is-open' : ''}`}><div className="sidebar-brand"><Brand /><button className="icon-button mobile-close" aria-label="Закрыть меню" onClick={() => setMobileMenu(false)}><X size={21} /></button></div><div className="workspace-label">ЛИЧНЫЙ КАБИНЕТ</div>
      <nav aria-label="Разделы кабинета">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${tab === id ? 'active' : ''}`} aria-current={tab === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={19} /><span>{label}</span>{tab === id && <span className="nav-dot" />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-tip"><span className="small-icon"><BookOpen size={19} /></span><strong>Развитие — это путь</strong><p>Сравнивайте навыки с целью и отмечайте свои достижения.</p><button onClick={() => navigate('trajectory')}>Посмотреть маршрут<ArrowUpRight size={16} /></button></div><div className="sidebar-user"><span className="avatar">{initials(profile?.full_name ?? session.user.username)}</span><div><strong>{profile?.full_name ?? session.user.username}</strong><span>{session.user.role === 'hr' ? 'HR · личный профиль' : 'Сотрудник'}</span></div><button className="icon-button" aria-label="Выйти" title="Выйти" onClick={logout} disabled={loggingOut}>{loggingOut ? <LoaderCircle className="spin" size={18} /> : <LogOut size={18} />}</button></div></div>
    </aside>
    <div className="workspace"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Открыть меню" onClick={() => setMobileMenu(true)}><Menu size={21} /></button><span>Личный кабинет</span><span className="breadcrumb-slash">/</span><strong>{tabs.find(item => item.id === tab)?.label}</strong></div><div className="topbar-right"><span className="private-label"><ShieldCheck size={15} />Личный доступ</span><span className="avatar small">{initials(profile?.full_name ?? session.user.username)}</span></div></header>
      <main id="main-content" className="main-content">
        {!session.user.employee_id ? <section className="empty-state large"><span className="small-icon"><ShieldCheck size={26} /></span><h1>У этой учётной записи нет личного профиля</h1><p>Вы вошли как HR. Кабинет показывает развитие конкретного сотрудника. Для просмотра своих навыков войдите под учётной записью сотрудника или попросите администратора привязать ваш профиль.</p><button className="button primary" onClick={logout} disabled={loggingOut}>Выйти и сменить аккаунт<ArrowRight size={17} /></button></section> : <>
          <div className="page-heading"><div><span className="eyebrow">CAREER QUEST</span><h1>{tabs.find(item => item.id === tab)?.label}</h1><p>{tab === 'overview' ? 'Всё, что нужно для следующего шага в карьере.' : tab === 'skills' ? 'Ваши сильные стороны и пространство для роста.' : tab === 'history' ? 'Опыт, который становится частью вашего развития.' : 'От сегодняшних навыков — к вашей карьерной цели.'}</p></div><button className="button refresh-button" onClick={() => setRevision(v => v + 1)} disabled={busy} aria-label="Обновить данные"><RefreshCw size={16} className={busy ? 'spin' : ''} /><span>Обновить</span></button></div>
          {error && <div className="error-banner" role="alert"><div><strong>Не удалось обновить данные</strong><p>{error}{data ? ' Ниже показана последняя успешная загрузка.' : ''}</p></div><button className="button" onClick={() => setRevision(v => v + 1)} disabled={busy}>Повторить</button></div>}
          {!data && busy && <div className="loading-state" role="status"><LoaderCircle className="spin" size={28} /><h2>Собираем ваш кабинет</h2><p>Загружаем профиль, навыки и историю обучения…</p></div>}
          {data && <>{tab === 'overview' && <Overview data={data} navigate={navigate} />}{tab === 'skills' && <SkillsView data={data} />}{tab === 'history' && <HistoryView data={data} />}{tab === 'trajectory' && <TrajectoryView data={data} navigate={navigate} />}<footer className="page-footer"><span>Career Quest · Ваш маршрут развития</span><span>Срез данных: {dateLabel(data.trajectory.as_of_date)}</span></footer></>}
        </>}
      </main>
    </div>
  </div>
}
