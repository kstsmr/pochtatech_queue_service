import { ArrowLeft, ArrowRight, Clock3 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { queueApi } from '../api/client'
import { BranchSelect } from '../components/BranchSelect'
import { ServiceSelect } from '../components/ServiceSelect'
import { useBranches, useServices, useSlots } from '../hooks/useCatalog'
import { saveTicketSession } from '../lib/ticketSession'

function toDateInputValue(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function BookingPage() {
  const [searchParams] = useSearchParams()
  const branches = useBranches()
  const [branchId, setBranchId] = useState(searchParams.get('branch') ?? '')
  const services = useServices(branchId)
  const [serviceId, setServiceId] = useState('')
  const [date, setDate] = useState(() => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    return toDateInputValue(tomorrow)
  })
  const [slotId, setSlotId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())
  const navigate = useNavigate()
  const minDate = toDateInputValue(new Date())
  const maxDate = new Date()
  maxDate.setDate(maxDate.getDate() + 60)

  const selectedBranch = branches.data.find((branch) => branch.id === branchId)
  const selectedService = services.data.find((service) => service.id === serviceId)
  const slots = useSlots(branchId, serviceId, date)
  const selectedSlot = slots.data.find((slot) => slot.id === slotId)
  const isComplete = Boolean(selectedBranch && selectedService && selectedSlot)
  const timeGroups = [
    { label: 'Утро', from: 0, to: 12 },
    { label: 'День', from: 12, to: 17 },
    { label: 'Вечер', from: 17, to: 24 },
  ].map((group) => ({
    ...group,
    slots: slots.data.filter((slot) => {
      if (!selectedBranch) return false
      const hour = Number(new Intl.DateTimeFormat('ru-RU', {
        hour: '2-digit', hourCycle: 'h23', timeZone: selectedBranch.timezone,
      }).format(new Date(slot.starts_at)))
      return hour >= group.from && hour < group.to
    }),
  })).filter((group) => group.slots.length > 0)

  function resetSubmission() {
    setSubmitError(null)
    setIdempotencyKey(crypto.randomUUID())
  }

  function changeBranch(value: string) {
    setBranchId(value)
    setServiceId('')
    setSlotId('')
    resetSubmission()
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedBranch || !selectedService || !selectedSlot || submitting) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const ticket = await queueApi.createBooking(branchId, serviceId, slotId, idempotencyKey)
      saveTicketSession(ticket)
      navigate('/ticket', { state: { justSaved: true } })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Не удалось создать запись')
    } finally {
      setSubmitting(false)
    }
  }

  const selectedTime = selectedSlot && selectedBranch
    ? new Date(selectedSlot.starts_at).toLocaleTimeString('ru-RU', {
        hour: '2-digit', minute: '2-digit', timeZone: selectedBranch.timezone,
      })
    : ''

  return (
    <section className="flow-page">
      <div className="flow-heading">
        <Link className="back-link" to="/"><ArrowLeft size={18} aria-hidden="true" /> Назад</Link>
        <p className="route-kicker"><span aria-hidden="true">02</span> Предварительная запись</p>
        <h1>Запись в отделение</h1>
        <p>Выберите отделение, услугу и время. Свободные интервалы рассчитаны по графику и числу окон.</p>
      </div>

      <ol className="flow-status" aria-label="Прогресс записи">
        <li className={branchId ? 'complete' : 'current'}><span>1</span>Отделение</li>
        <li className={serviceId ? 'complete' : branchId ? 'current' : ''}><span>2</span>Услуга</li>
        <li className={slotId ? 'complete' : serviceId ? 'current' : ''}><span>3</span>Время</li>
      </ol>

      <div className="booking-layout">
        <form className="booking-form" onSubmit={submit}>
          <fieldset>
            <legend><span>1</span> Отделение и услуга</legend>
            <BranchSelect
              branches={branches.data}
              value={branchId}
              loading={branches.loading}
              error={branches.error}
              onChange={changeBranch}
              search={branches.search}
              onSearch={branches.setSearch}
              hint="Можно изменить отделение — список услуг обновится"
            />
            <ServiceSelect
              services={services.data}
              value={serviceId}
              loading={services.loading}
              error={services.error}
              disabled={!branchId}
              onChange={(value) => { setServiceId(value); setSlotId(''); resetSubmission() }}
            />
          </fieldset>

          <fieldset>
            <legend><span>2</span> Когда</legend>
            <div className="form-field">
              <label htmlFor="booking-date">Дата визита</label>
              <input
                id="booking-date"
                type="date"
                min={minDate}
                max={toDateInputValue(maxDate)}
                value={date}
                onChange={(event) => { setDate(event.target.value); setSlotId(''); resetSubmission() }}
                required
              />
            </div>
            <div className="form-field">
              <span className="field-label">Время</span>
              <div className="time-groups" role="radiogroup" aria-label="Время визита">
                {timeGroups.map((group) => <div className="time-group" key={group.label}>
                  <strong className="time-group-title">{group.label}</strong>
                  <div className="time-grid">
                  {group.slots.map((slot) => {
                  const option = selectedBranch
                    ? new Date(slot.starts_at).toLocaleTimeString('ru-RU', {
                        hour: '2-digit', minute: '2-digit', timeZone: selectedBranch.timezone,
                      })
                    : ''
                  return (
                  <button
                    key={slot.id}
                    type="button"
                    role="radio"
                    aria-checked={slotId === slot.id}
                    className={slotId === slot.id ? 'time-option active' : 'time-option'}
                    onClick={() => { setSlotId(slot.id); resetSubmission() }}
                  >
                    {option}
                  </button>
                  )
                  })}
                  </div>
                </div>)}
              </div>
              {slots.loading && <p className="field-message hint" role="status">Проверяем свободное время…</p>}
              {!slots.loading && serviceId && !slots.error && slots.data.length === 0 && (
                <p className="field-message hint">На эту дату свободного времени нет. Выберите другую дату.</p>
              )}
              {slots.error && <p className="field-message error" role="alert">{slots.error}</p>}
            </div>
          </fieldset>

          {submitError && <p className="submit-error" role="alert">{submitError}</p>}
          <button className="button primary" type="submit" disabled={!isComplete || submitting}>
            {submitting ? 'Создаём запись…' : 'Подтвердить запись'}
            <ArrowRight size={20} aria-hidden="true" />
          </button>
        </form>

        <aside className="visit-summary" aria-label="Сводка визита">
          <p className="summary-label">Детали записи</p>
          <div className="summary-code" aria-hidden="true">{selectedBranch?.postal_code ?? 'ПОЧТА'}</div>
          <dl>
            <div><dt>Отделение</dt><dd>{selectedBranch?.address ?? 'Не выбрано'}</dd></div>
            <div><dt>Услуга</dt><dd>{selectedService?.name ?? 'Не выбрана'}</dd></div>
            <div><dt>Время</dt><dd>{selectedTime ? `${date.split('-').reverse().join('.')} · ${selectedTime}` : 'Не выбрано'}</dd></div>
          </dl>
          <p className="summary-footnote"><Clock3 size={17} aria-hidden="true" /> Приходите немного заранее — талон станет активным до выбранного времени.</p>
        </aside>
      </div>
    </section>
  )
}
