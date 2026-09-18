import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  DoorClosed,
  Gauge,
  ListChecks,
  LogOut,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Users,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { ApiClientError, managerApi, staffApi } from '../api/client'
import type { ManagerDashboard, ManagerPriorityUpdate, StaffSession, StaffTicket } from '../api/types'
import { clearStaffSession, loadStaffSession } from '../lib/staffSession'

type ManagerView = 'overview' | 'queue' | 'settings' | 'alerts'

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

export function ManagerPage() {
  const session = loadStaffSession()
  if (!session || session.role !== 'manager') return <Navigate to="/staff" replace />
  return <ManagerWorkspace session={session} />
}

function ManagerWorkspace({ session }: { session: StaffSession }) {
  const [view, setView] = useState<ManagerView>('overview')
  const [dashboard, setDashboard] = useState<ManagerDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await managerApi.getDashboard(session.token, signal)
      setDashboard(next)
      setError(null)
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      if (requestError instanceof ApiClientError && requestError.status === 401) {
        clearStaffSession()
        window.location.assign('/staff')
        return
      }
      setError(requestError instanceof Error ? requestError.message : 'Не удалось обновить данные')
    }
  }, [session.token])

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

  async function act(key: string, operation: () => Promise<unknown>, success: string) {
    if (busy) return
    setBusy(key)
    setNotice(null)
    setError(null)
    try {
      await operation()
      setNotice(success)
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Операция не выполнена')
    } finally {
      setBusy(null)
    }
  }

  async function logout() {
    try {
      await staffApi.logout(session.token)
    } finally {
      clearStaffSession()
      window.location.assign('/staff')
    }
  }

  const views = [
    { id: 'overview' as const, label: 'Обзор', icon: BarChart3 },
    { id: 'queue' as const, label: 'Очередь', icon: Users },
    { id: 'settings' as const, label: 'Окна и правила', icon: Settings2 },
    { id: 'alerts' as const, label: 'Отклонения', icon: AlertTriangle },
  ]

  return (
    <main className="manager-workspace">
      <header className="staff-topbar manager-topbar">
        <Link className="staff-brand" to="/"><span>О</span><strong>Руководитель</strong></Link>
        <div className="staff-location"><small>{session.branch.postal_code}</small><strong>{session.branch.address}</strong></div>
        <div className="staff-user"><span><strong>{session.display_name}</strong><small>{session.employee_code}</small></span></div>
        <button className="icon-command" type="button" title="Обновить" onClick={() => void refresh()}><RefreshCw size={18} /></button>
        <button className="icon-command" type="button" title="Выйти" onClick={() => void logout()}><LogOut size={18} /></button>
      </header>

      <div className="manager-shell">
        <nav className="manager-nav" aria-label="Разделы кабинета">
          <div className="manager-nav-title">Отделение {session.branch.postal_code}</div>
          {views.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={view === id ? 'active' : ''} onClick={() => setView(id)}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span>
              {id === 'alerts' && dashboard && dashboard.deviations.length > 0 && <b>{dashboard.deviations.length}</b>}
            </button>
          ))}
          <div className="manager-live"><span className={error ? 'status-dot offline' : 'status-dot'} />{error ? 'Нет связи' : 'Данные обновляются автоматически'}</div>
        </nav>

        <section className="manager-content">
          <div className="manager-page-heading">
            <div><p className="staff-section-label">Панель отделения</p><h1>{views.find((item) => item.id === view)?.label}</h1></div>
            {dashboard && <time>Обновлено {new Date(dashboard.generated_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>}
          </div>
          {(error || notice) && <div className={error ? 'manager-message error' : 'manager-message'} role="status">{error ?? notice}</div>}
          {!dashboard ? <div className="manager-loading">Получаем данные отделения…</div> : (
            <>
              {view === 'overview' && <Overview dashboard={dashboard} onCloseWindow={(id) => void act(`close-${id}`, () => managerApi.closeWindow(session.token, id), 'Окно закрыто или завершает текущего клиента')} busy={busy} />}
              {view === 'queue' && <QueueView queue={dashboard.queue} />}
              {view === 'settings' && <SettingsView dashboard={dashboard} token={session.token} busy={busy} act={act} />}
              {view === 'alerts' && <AlertsView dashboard={dashboard} onResolve={(id) => void act(`incident-${id}`, () => managerApi.resolveIncident(session.token, id), 'Проблема отмечена решённой')} busy={busy} />}
            </>
          )}
        </section>
      </div>
    </main>
  )
}

function Overview({ dashboard, onCloseWindow, busy }: { dashboard: ManagerDashboard; onCloseWindow: (id: string) => void; busy: string | null }) {
  const metrics = dashboard.metrics
  const metricItems = [
    ['Сейчас ожидают', metrics.waiting_count, Users],
    ['Среднее ожидание', `${metrics.average_wait_minutes} мин`, Clock3],
    ['Максимум', `${metrics.maximum_wait_minutes} мин`, AlertTriangle],
    ['Обслужено сегодня', metrics.served_today, CheckCircle2],
    ['Открыто окон', `${metrics.open_windows} из ${metrics.total_windows}`, DoorClosed],
    ['Занято открытых окон', `${metrics.window_load_percent}%`, Gauge],
  ] as const
  return (
    <>
      <div className="manager-metrics">
        {metricItems.map(([label, value, Icon]) => <div key={label}><Icon size={18} /><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      <section className={`manager-recommendation recommendation-${dashboard.recommendation.level}`}>
        <SlidersHorizontal size={22} />
        <div><strong>{dashboard.recommendation.title}</strong><span>{dashboard.recommendation.detail}</span></div>
        {dashboard.recommendation.suggested_windows > 0 && <b>+{dashboard.recommendation.suggested_windows} {dashboard.recommendation.suggested_windows === 1 ? 'окно' : 'окна'}</b>}
      </section>
      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">Состояние сейчас</p><h2>Окна отделения</h2></div></div>
        <div className="manager-window-table">
          {dashboard.windows.map((item) => (
            <div key={item.id}>
              <strong>Окно {item.number}</strong>
              <span className={`window-state state-${item.status}`}>{item.status === 'closed' ? 'Закрыто' : item.status === 'open' ? 'Открыто' : 'Завершает'}</span>
              <span>{item.operator_code ?? 'Оператор не назначен'}</span>
              <span>{item.active_ticket ? `Талон О / ${String(item.active_ticket.ticket_number).padStart(3, '0')}` : 'Свободно'}</span>
              <button type="button" className="icon-command bordered" title="Закрыть окно" disabled={item.status === 'closed' || Boolean(busy)} onClick={() => onCloseWindow(item.id)}><DoorClosed size={17} /></button>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}

function QueueView({ queue }: { queue: StaffTicket[] }) {
  return (
    <section className="manager-section manager-queue-section">
      <div className="manager-section-heading"><div><p className="staff-section-label">В реальном времени</p><h2>{queue.length} активных талонов</h2></div></div>
      <div className="manager-queue-table">
        <div className="table-head"><span>Талон</span><span>Источник</span><span>Услуга</span><span>Статус</span><span>Ожидание</span><span>Окно</span></div>
        {queue.length === 0 && <p className="manager-empty">Активных талонов нет</p>}
        {queue.map((ticket) => (
          <div key={ticket.id}>
            <strong>О / {String(ticket.ticket_number).padStart(3, '0')}</strong>
            <span className={`source-tag source-${ticket.source}`}>{sourceLabels[ticket.source]}</span>
            <span>{ticket.service_name}</span><span>{statusLabels[ticket.status]}</span>
            <span>{ticket.waiting_minutes} мин.</span><span>{ticket.window_number ? `№ ${ticket.window_number}` : '—'}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function SettingsView({ dashboard, token, busy, act }: {
  dashboard: ManagerDashboard
  token: string
  busy: string | null
  act: (key: string, operation: () => Promise<unknown>, success: string) => Promise<void>
}) {
  const [windowDrafts, setWindowDrafts] = useState<Record<string, string[]>>(() => Object.fromEntries(dashboard.windows.map((item) => [item.id, item.service_ids])))
  const [serviceMinutes, setServiceMinutes] = useState<Record<string, number>>(() => Object.fromEntries(dashboard.services.map((item) => [item.id, Math.round(item.average_service_seconds / 60)])))
  const config = dashboard.priority_rule.config
  const [priority, setPriority] = useState<ManagerPriorityUpdate>({
    early_minutes: config.early_minutes,
    grace_minutes: config.grace_minutes,
    prebooking_max_wait_minutes: config.max_wait_minutes.prebooking,
    qr_max_wait_minutes: config.max_wait_minutes.qr,
    walk_in_max_wait_minutes: config.max_wait_minutes.walk_in,
    appointment_level: config.levels.appointment,
    qr_level: config.levels.qr,
    walk_in_level: config.levels.walk_in,
    late_prebooking_level: config.levels.late_prebooking,
  })

  function toggleWindowService(windowId: string, serviceId: string) {
    setWindowDrafts((current) => {
      const selected = current[windowId] ?? []
      return { ...current, [windowId]: selected.includes(serviceId) ? selected.filter((id) => id !== serviceId) : [...selected, serviceId] }
    })
  }

  return (
    <div className="manager-settings-stack">
      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">Доступность</p><h2>Услуги отделения</h2></div><p>Среднее время используется для записи и прогноза.</p></div>
        <div className="manager-service-list">
          {dashboard.services.map((service) => (
            <div key={service.id}>
              <span><strong>{service.name}</strong><small>{service.active ? 'Доступна клиентам' : 'Приостановлена'}</small></span>
              <label><span>Минут</span><input type="number" min="1" max="120" value={serviceMinutes[service.id] ?? 1} onChange={(event) => setServiceMinutes((current) => ({ ...current, [service.id]: Number(event.target.value) }))} /></label>
              <button className={`manager-toggle ${service.active ? 'active' : ''}`} type="button" aria-pressed={service.active} disabled={Boolean(busy)} onClick={() => void act(`service-${service.id}`, () => managerApi.updateService(token, service.id, !service.active, (serviceMinutes[service.id] ?? 1) * 60), service.active ? 'Услуга приостановлена' : 'Услуга доступна')}>{service.active ? 'Включена' : 'Выключена'}</button>
              <button className="button secondary inline-button compact" type="button" disabled={Boolean(busy)} onClick={() => void act(`duration-${service.id}`, () => managerApi.updateService(token, service.id, service.active, (serviceMinutes[service.id] ?? 1) * 60), 'Среднее время обновлено')}>Сохранить</button>
            </div>
          ))}
        </div>
      </section>

      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">Распределение</p><h2>Услуги по окнам</h2></div><p>Настройки меняются только у закрытого окна.</p></div>
        <div className="manager-window-settings">
          {dashboard.windows.map((item) => (
            <div key={item.id}>
              <header><strong>Окно {item.number}</strong><span className={`window-state state-${item.status}`}>{item.status === 'closed' ? 'Закрыто' : 'Работает'}</span></header>
              <div>
                {dashboard.services.filter((service) => service.active).map((service) => (
                  <label key={service.id}><input type="checkbox" disabled={item.status !== 'closed'} checked={(windowDrafts[item.id] ?? []).includes(service.id)} onChange={() => toggleWindowService(item.id, service.id)} /><span>{service.name}</span></label>
                ))}
              </div>
              <button className="button secondary inline-button compact" type="button" disabled={item.status !== 'closed' || !(windowDrafts[item.id]?.length) || Boolean(busy)} onClick={() => void act(`window-${item.id}`, () => managerApi.updateWindowServices(token, item.id, windowDrafts[item.id]), 'Услуги окна обновлены')}>Сохранить</button>
            </div>
          ))}
        </div>
      </section>

      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">Версия {dashboard.priority_rule.version}</p><h2>Правила приоритета</h2></div><p>Меньше число — выше приоритет. Просроченные талоны всегда получают уровень 0.</p></div>
        <form className="priority-form" onSubmit={(event) => { event.preventDefault(); void act('priority', () => managerApi.updatePriority(token, priority), 'Новая версия правил применена') }}>
          <fieldset><legend>Запись ко времени</legend><NumberField label="Активна заранее, мин." value={priority.early_minutes} onChange={(value) => setPriority({ ...priority, early_minutes: value })} /><NumberField label="Допустимое опоздание, мин." value={priority.grace_minutes} onChange={(value) => setPriority({ ...priority, grace_minutes: value })} /><NumberField label="Максимальное ожидание, мин." value={priority.prebooking_max_wait_minutes} onChange={(value) => setPriority({ ...priority, prebooking_max_wait_minutes: value })} /></fieldset>
          <fieldset><legend>Предел ожидания</legend><NumberField label="QR-талон, мин." value={priority.qr_max_wait_minutes} onChange={(value) => setPriority({ ...priority, qr_max_wait_minutes: value })} /><NumberField label="Живая очередь, мин." value={priority.walk_in_max_wait_minutes} onChange={(value) => setPriority({ ...priority, walk_in_max_wait_minutes: value })} /></fieldset>
          <fieldset><legend>Уровни</legend><NumberField label="Запись" value={priority.appointment_level} onChange={(value) => setPriority({ ...priority, appointment_level: value })} /><NumberField label="QR" value={priority.qr_level} onChange={(value) => setPriority({ ...priority, qr_level: value })} /><NumberField label="Живая очередь" value={priority.walk_in_level} onChange={(value) => setPriority({ ...priority, walk_in_level: value })} /><NumberField label="Опоздавшая запись" value={priority.late_prebooking_level} onChange={(value) => setPriority({ ...priority, late_prebooking_level: value })} /></fieldset>
          <button className="button primary manager-save-priority" type="submit" disabled={Boolean(busy)}>Применить новую версию <ListChecks size={18} /></button>
        </form>
      </section>
    </div>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="manager-number-field"><span>{label}</span><input type="number" min="0" max="240" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>
}

function AlertsView({ dashboard, onResolve, busy }: { dashboard: ManagerDashboard; onResolve: (id: string) => void; busy: string | null }) {
  return (
    <div className="manager-alert-grid">
      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">Требуют внимания</p><h2>Отклонения</h2></div></div>
        <div className="deviation-list">
          {dashboard.deviations.length === 0 && <p className="manager-empty">Отклонений нет</p>}
          {dashboard.deviations.map((item) => <div key={item.id}><AlertTriangle size={17} /><span><strong>{item.label}</strong><small>{item.detail}</small></span><time>{new Date(item.occurred_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</time></div>)}
        </div>
      </section>
      <section className="manager-section">
        <div className="manager-section-heading"><div><p className="staff-section-label">От операторов</p><h2>Открытые проблемы</h2></div></div>
        <div className="incident-list">
          {dashboard.incidents.length === 0 && <p className="manager-empty">Открытых проблем нет</p>}
          {dashboard.incidents.map((item) => <div key={item.id}><span><strong>{item.category === 'technical' ? 'Техническая' : 'Операционная'}</strong><small>{item.description}</small><em>{item.window_number ? `Окно ${item.window_number}` : 'Без окна'} · {item.actor_id}</em></span><button className="icon-command bordered" type="button" title="Отметить решённой" disabled={Boolean(busy)} onClick={() => onResolve(item.id)}><CheckCircle2 size={18} /></button></div>)}
        </div>
      </section>
      <section className="manager-section manager-unfinished">
        <div className="manager-section-heading"><div><p className="staff-section-label">Не завершены</p><h2>Активные талоны</h2></div><b>{dashboard.metrics.unfinished_tickets}</b></div>
        <QueueView queue={dashboard.unfinished_tickets} />
      </section>
    </div>
  )
}
