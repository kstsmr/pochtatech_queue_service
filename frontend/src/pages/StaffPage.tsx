import {
  AlertTriangle,
  ArrowLeft,
  ArrowRightLeft,
  BellRing,
  CheckCircle2,
  Clock3,
  DoorClosed,
  DoorOpen,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  UserRound,
  UserX,
  Users,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ApiClientError, staffApi } from '../api/client'
import type { StaffSession, StaffTicket, StaffWindow } from '../api/types'
import { BranchSelect } from '../components/BranchSelect'
import { useBranches, useServices } from '../hooks/useCatalog'
import { clearStaffSession, loadStaffSession, saveStaffSession } from '../lib/staffSession'

const sourceLabels: Record<StaffTicket['source'], string> = {
  prebooking: 'Запись',
  qr: 'QR',
  walk_in: 'Живая',
}

const statusLabels: Record<StaffTicket['status'], string> = {
  booked: 'Ко времени',
  waiting: 'Ожидает',
  called: 'Вызван',
  serving: 'Обслуживается',
  served: 'Завершён',
  no_show: 'Не явился',
  cancelled: 'Отменён',
}

export function StaffPage() {
  const navigate = useNavigate()
  const branches = useBranches()
  const [session, setSession] = useState<StaffSession | null>(() => loadStaffSession())
  const [branchId, setBranchId] = useState('')
  const [employeeCode, setEmployeeCode] = useState('operator-1')
  const [pin, setPin] = useState('')
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!branchId || !employeeCode.trim() || !pin || loginBusy) return
    setLoginBusy(true)
    setLoginError(null)
    try {
      const created = await staffApi.login(branchId, employeeCode.trim(), pin)
      saveStaffSession(created)
      setSession(created)
      setPin('')
      if (created.role === 'manager') navigate('/manager', { replace: true })
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : 'Не удалось открыть рабочее место')
    } finally {
      setLoginBusy(false)
    }
  }

  if (!session) {
    return (
      <main className="staff-login-page">
        <section className="staff-login-copy">
          <Link className="back-link" to="/"><ArrowLeft size={18} aria-hidden="true" /> Клиентский сервис</Link>
          <p className="route-kicker"><span aria-hidden="true">РМ</span> Вход для сотрудников</p>
          <h1>Рабочее место отделения</h1>
          <p>После входа откроется рабочее место оператора или панель руководителя — в соответствии с ролью сотрудника.</p>
        </section>
        <form className="staff-login-form" onSubmit={login}>
          <div className="staff-login-mark"><UserRound size={24} aria-hidden="true" /><span>Учётная запись сотрудника</span></div>
          <BranchSelect
            branches={branches.data}
            value={branchId}
            loading={branches.loading}
            error={branches.error}
            onChange={setBranchId}
            search={branches.search}
            onSearch={branches.setSearch}
          />
          <label className="staff-field">
            <span>Код сотрудника</span>
            <input value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} maxLength={50} required />
          </label>
          <label className="staff-field">
            <span>PIN</span>
            <input type="password" inputMode="numeric" value={pin} onChange={(event) => setPin(event.target.value)} minLength={4} required />
          </label>
          {loginError && <p className="submit-error" role="alert">{loginError}</p>}
          <button className="button primary" type="submit" disabled={!branchId || loginBusy}>
            {loginBusy ? 'Проверяем…' : 'Войти'} <DoorOpen size={19} aria-hidden="true" />
          </button>
        </form>
      </main>
    )
  }

  if (session.role === 'manager') return <Navigate to="/manager" replace />

  async function logout(token: string) {
    try {
      await staffApi.logout(token)
    } finally {
      clearStaffSession()
      setSession(null)
    }
  }

  return <StaffWorkspace session={session} onLogout={() => void logout(session.token)} />
}

function StaffWorkspace({ session, onLogout }: { session: StaffSession; onLogout: () => void }) {
  const services = useServices(session.branch.id)
  const [windows, setWindows] = useState<StaffWindow[]>([])
  const [queue, setQueue] = useState<StaffTicket[]>([])
  const [selectedWindowId, setSelectedWindowId] = useState('')
  const [selectedServices, setSelectedServices] = useState<string[]>([])
  const [walkInService, setWalkInService] = useState('')
  const [redirectService, setRedirectService] = useState('')
  const [redirectWindow, setRedirectWindow] = useState('')
  const [incidentCategory, setIncidentCategory] = useState<'technical' | 'operational'>('technical')
  const [incidentText, setIncidentText] = useState('')
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextWindows, nextQueue] = await Promise.all([
        staffApi.getWindows(session.token, signal),
        staffApi.getQueue(session.token, signal),
      ])
      setWindows(nextWindows)
      setQueue(nextQueue)
      setLastUpdated(new Date())
      setError(null)
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      if (requestError instanceof ApiClientError && requestError.status === 401) {
        clearStaffSession()
        onLogout()
        return
      }
      setError(requestError instanceof Error ? requestError.message : 'Не удалось обновить рабочее место')
    }
  }, [onLogout, session.token])

  useEffect(() => {
    const controller = new AbortController()
    const initial = window.setTimeout(() => void refresh(controller.signal), 0)
    const interval = window.setInterval(() => void refresh(), 3000)
    return () => {
      controller.abort()
      window.clearTimeout(initial)
      window.clearInterval(interval)
    }
  }, [refresh])

  const ownedWindow = windows.find((windowItem) => windowItem.owned_by_current_session) ?? null
  const activeTicket = ownedWindow?.active_ticket ?? null
  const waitingQueue = useMemo(() => queue.filter((ticket) => ticket.status === 'waiting' || ticket.status === 'booked'), [queue])
  const availableRedirectWindows = windows.filter((windowItem) => windowItem.status === 'open' && windowItem.id !== ownedWindow?.id)

  async function act(name: string, operation: () => Promise<unknown>, success: string) {
    if (busyAction) return
    setBusyAction(name)
    setError(null)
    setNotice(null)
    try {
      await operation()
      setNotice(success)
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Операция не выполнена')
    } finally {
      setBusyAction(null)
    }
  }

  function toggleService(serviceId: string) {
    setSelectedServices((current) => current.includes(serviceId)
      ? current.filter((item) => item !== serviceId)
      : [...current, serviceId])
  }

  return (
    <main className="staff-workspace">
      <header className="staff-topbar">
        <Link className="staff-brand" to="/"><span>О</span><strong>Рабочее место</strong></Link>
        <div className="staff-location"><small>{session.branch.postal_code}</small><strong>{session.branch.address}</strong></div>
        <div className="staff-user"><UserRound size={18} aria-hidden="true" /><span><strong>{session.display_name}</strong><small>{session.employee_code}</small></span></div>
        <button className="icon-command" type="button" title="Обновить" onClick={() => void refresh()}><RefreshCw size={18} /></button>
        <button className="icon-command" type="button" title={ownedWindow ? 'Сначала закройте окно' : 'Завершить смену'} disabled={Boolean(ownedWindow)} onClick={onLogout}><LogOut size={18} /></button>
      </header>

      <div className="staff-statusline" role="status">
        <span className={error ? 'status-dot offline' : 'status-dot'} />
        {error ?? notice ?? (lastUpdated ? `Данные обновлены в ${lastUpdated.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : 'Подключаемся к очереди')}
      </div>

      <div className="staff-grid">
        <section className="staff-main-panel">
          {!ownedWindow ? (
            <div className="window-setup">
              <p className="staff-section-label">Начало работы</p>
              <h1>Выберите свободное окно</h1>
              <div className="window-choice-grid">
                {windows.map((windowItem) => (
                  <button
                    key={windowItem.id}
                    type="button"
                    className={`window-choice ${selectedWindowId === windowItem.id ? 'active' : ''}`}
                    disabled={windowItem.status !== 'closed'}
                    onClick={() => setSelectedWindowId(windowItem.id)}
                  >
                    <strong>Окно {windowItem.number}</strong>
                    <span>{windowItem.status === 'closed' ? 'Свободно' : `Работает ${windowItem.operator_code ?? ''}`}</span>
                  </button>
                ))}
              </div>
              <p className="staff-section-label">Услуги окна</p>
              <div className="service-toggle-grid">
                {services.data.map((service) => (
                  <label key={service.id} className={selectedServices.includes(service.id) ? 'active' : ''}>
                    <input type="checkbox" checked={selectedServices.includes(service.id)} onChange={() => toggleService(service.id)} />
                    <span>{service.name}</span>
                  </label>
                ))}
              </div>
              <button
                className="button primary staff-primary-command"
                type="button"
                disabled={!selectedWindowId || selectedServices.length === 0 || Boolean(busyAction)}
                onClick={() => void act('open', () => staffApi.openWindow(session.token, selectedWindowId, selectedServices), 'Окно открыто')}
              >
                Открыть окно <DoorOpen size={20} aria-hidden="true" />
              </button>
            </div>
          ) : (
            <>
              <div className="window-command-header">
                <div><p className="staff-section-label">Текущее рабочее место</p><h1>Окно {ownedWindow.number}</h1></div>
                <span className={`window-state state-${ownedWindow.status}`}>{ownedWindow.status === 'open' ? 'Открыто' : 'Закрывается'}</span>
                <button
                  className="button secondary inline-button"
                  type="button"
                  disabled={Boolean(busyAction) || ownedWindow.status === 'draining'}
                  onClick={() => void act('close', () => staffApi.closeWindow(session.token, ownedWindow.id), activeTicket ? 'Окно закроется после клиента' : 'Окно закрыто')}
                >
                  <DoorClosed size={18} /> Закрыть окно
                </button>
              </div>

              {activeTicket ? (
                <article className="active-client">
                  <div className="active-ticket-number"><small>Талон</small><strong>О / {String(activeTicket.ticket_number).padStart(3, '0')}</strong></div>
                  <div className="active-client-info">
                    <span className={`source-tag source-${activeTicket.source}`}>{sourceLabels[activeTicket.source]}</span>
                    <h2>{activeTicket.service_name}</h2>
                    <p>{statusLabels[activeTicket.status]} · ожидание {activeTicket.waiting_minutes} мин.</p>
                  </div>
                  <div className="active-actions">
                    {activeTicket.status === 'called' && (
                      <>
                        <button className="button primary" type="button" disabled={Boolean(busyAction)} onClick={() => void act('start', () => staffApi.startTicket(session.token, activeTicket.id), 'Обслуживание начато')}>
                          Начать обслуживание <Play size={18} />
                        </button>
                        <button className="button secondary inline-button" type="button" disabled={Boolean(busyAction)} onClick={() => void act('recall', () => staffApi.recallTicket(session.token, activeTicket.id), 'Вызов повторён')}>
                          <BellRing size={18} /> Повторить вызов
                        </button>
                        <button className="button secondary inline-button danger-command" type="button" disabled={Boolean(busyAction)} onClick={() => void act('no-show', () => staffApi.markNoShow(session.token, activeTicket.id), 'Зафиксирована неявка')}>
                          <UserX size={18} /> Не явился
                        </button>
                      </>
                    )}
                    {activeTicket.status === 'serving' && (
                      <button className="button secondary inline-button" type="button" disabled={Boolean(busyAction)} onClick={() => void act('complete', () => staffApi.completeTicket(session.token, activeTicket.id), 'Клиент обслужен')}>
                        <CheckCircle2 size={18} /> Завершить
                      </button>
                    )}
                    <button className="button secondary inline-button" type="button" disabled={Boolean(busyAction)} onClick={() => void act('return', () => staffApi.returnTicket(session.token, activeTicket.id), 'Талон возвращён в очередь')}>
                      <RotateCcw size={18} /> Вернуть
                    </button>
                  </div>
                  <div className="redirect-controls">
                    <select value={redirectService} onChange={(event) => setRedirectService(event.target.value)} aria-label="Новая услуга">
                      <option value="">Сохранить услугу</option>
                      {services.data.filter((service) => service.id !== activeTicket.service_id).map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}
                    </select>
                    <select value={redirectWindow} onChange={(event) => setRedirectWindow(event.target.value)} aria-label="Целевое окно">
                      <option value="">Любое подходящее окно</option>
                      {availableRedirectWindows.map((windowItem) => <option key={windowItem.id} value={windowItem.id}>Окно {windowItem.number}</option>)}
                    </select>
                    <button className="icon-command bordered" type="button" title="Перенаправить" disabled={Boolean(busyAction) || (!redirectService && !redirectWindow)} onClick={() => void act('redirect', () => staffApi.redirectTicket(session.token, activeTicket.id, redirectService, redirectWindow), 'Талон перенаправлен')}>
                      <ArrowRightLeft size={19} />
                    </button>
                  </div>
                </article>
              ) : (
                <div className="call-zone">
                  <Users size={42} aria-hidden="true" />
                  <div><h2>Окно свободно</h2><p>{waitingQueue.length ? `${waitingQueue.length} клиентов ожидают обслуживания` : 'Подходящих клиентов пока нет'}</p></div>
                  <button className="button primary staff-call-button" type="button" disabled={Boolean(busyAction) || ownedWindow.status !== 'open'} onClick={() => void act('call', () => staffApi.callNext(session.token, ownedWindow.id), 'Клиент вызван')}>
                    Вызвать следующего <Send size={20} />
                  </button>
                </div>
              )}

              <div className="staff-inline-tool">
                <div><Plus size={18} /><span><strong>Живая очередь</strong><small>Добавить клиента без электронного талона</small></span></div>
                <select value={walkInService} onChange={(event) => setWalkInService(event.target.value)} aria-label="Услуга живой очереди">
                  <option value="">Выберите услугу</option>
                  {services.data.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}
                </select>
                <button className="button secondary inline-button" type="button" disabled={!walkInService || Boolean(busyAction)} onClick={() => void act('walk-in', () => staffApi.createWalkIn(session.token, walkInService), 'Клиент добавлен в очередь')}>Добавить</button>
              </div>
            </>
          )}
        </section>

        <aside className="staff-side-panel">
          <div className="queue-heading"><div><p className="staff-section-label">Очередь отделения</p><h2>{waitingQueue.length} ожидают</h2></div><Clock3 size={21} /></div>
          <div className="staff-queue-list">
            {queue.length === 0 && <p className="queue-empty">Активных талонов нет</p>}
            {queue.map((ticket) => (
              <div className="queue-row" key={ticket.id}>
                <strong>О / {String(ticket.ticket_number).padStart(3, '0')}</strong>
                <span className={`source-tag source-${ticket.source}`}>{sourceLabels[ticket.source]}</span>
                <div><b>{ticket.service_name}</b><small>{statusLabels[ticket.status]} · {ticket.waiting_minutes} мин.</small></div>
                {ticket.window_number && <em>Окно {ticket.window_number}</em>}
              </div>
            ))}
          </div>

          <form className="incident-form" onSubmit={(event) => {
            event.preventDefault()
            if (!incidentText.trim()) return
            void act('incident', () => staffApi.createIncident(session.token, incidentCategory, incidentText.trim(), ownedWindow?.id ?? null, activeTicket?.id ?? null), 'Проблема зафиксирована')
            setIncidentText('')
          }}>
            <div className="incident-heading"><AlertTriangle size={18} /><strong>Зафиксировать проблему</strong></div>
            <select value={incidentCategory} onChange={(event) => setIncidentCategory(event.target.value as 'technical' | 'operational')}>
              <option value="technical">Техническая</option>
              <option value="operational">Операционная</option>
            </select>
            <textarea value={incidentText} onChange={(event) => setIncidentText(event.target.value)} placeholder="Кратко опишите ситуацию" minLength={5} maxLength={1000} required />
            <button className="button secondary inline-button" type="submit" disabled={incidentText.trim().length < 5 || Boolean(busyAction)}>Сохранить</button>
          </form>
        </aside>
      </div>
    </main>
  )
}
