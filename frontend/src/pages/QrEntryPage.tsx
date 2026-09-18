import { ArrowLeft, Check, Keyboard, MapPin, QrCode, ScanLine } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { queueApi } from '../api/client'
import { ServiceSelect } from '../components/ServiceSelect'
import { useBranchByCode, useServices } from '../hooks/useCatalog'
import { saveTicketSession } from '../lib/ticketSession'

export function QrEntryPage() {
  const [searchParams] = useSearchParams()
  const scannedCode = searchParams.get('branch') ?? ''
  const validScannedCode = /^\d{6}$/.test(scannedCode)
  const [manualMode, setManualMode] = useState(!validScannedCode)
  const [code, setCode] = useState(() => validScannedCode ? scannedCode : '')
  const [serviceId, setServiceId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())
  const branchLookup = useBranchByCode(code)
  const branch = branchLookup.data
  const services = useServices(branch?.id ?? '')
  const selectedService = services.data.find((service) => service.id === serviceId)
  const codeComplete = code.length === 6
  const navigate = useNavigate()

  function resetSubmission() {
    setSubmitError(null)
    setIdempotencyKey(crypto.randomUUID())
  }

  function changeCode(value: string) {
    setCode(value.replace(/\D/g, '').slice(0, 6))
    setServiceId('')
    resetSubmission()
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!branch || !selectedService || submitting) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const ticket = await queueApi.joinQueue(code, serviceId, idempotencyKey)
      saveTicketSession(ticket)
      navigate('/ticket', { state: { justSaved: true } })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Не удалось получить талон')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="flow-page qr-page">
      <div className="flow-heading">
        <Link className="back-link" to="/"><ArrowLeft size={18} aria-hidden="true" /> Назад</Link>
        <p className="route-kicker"><span aria-hidden="true">03</span> В отделении</p>
        <h1>{validScannedCode && !manualMode ? 'Выберите услугу' : 'Получите талон в отделении'}</h1>
        <p>
          {validScannedCode && !manualMode
            ? 'QR-код определил отделение. Выберите, зачем вы пришли — талон появится на этом устройстве.'
            : 'Если камера не считала QR-код, введите шесть цифр с плаката рядом с ним.'}
        </p>
      </div>

      <div className="qr-layout">
        {validScannedCode && !manualMode ? (
          <div className="qr-scan-result">
            <div className="qr-scan-icon"><ScanLine size={38} aria-hidden="true" /><Check size={19} aria-hidden="true" /></div>
            <p>QR-код считан</p>
            {branchLookup.loading && <strong>Проверяем отделение…</strong>}
            {branch && <><strong>{branch.name}</strong><span><MapPin size={17} />{branch.address}</span><small>Код {branch.postal_code}</small></>}
            {branchLookup.error && <strong className="qr-scan-error">{branchLookup.error}</strong>}
            <button className="text-button" type="button" onClick={() => { setManualMode(true); setCode(''); setServiceId('') }}>Ввести код вручную</button>
          </div>
        ) : (
          <div className="qr-guide">
            <div className="qr-guide-mark" aria-hidden="true"><QrCode /></div>
            <p>Не получилось отсканировать</p>
            <strong>Введите код с плаката</strong>
            <ol>
              <li><span>1</span>Введите 6 цифр</li>
              <li><span>2</span>Проверьте адрес</li>
              <li><span>3</span>Выберите услугу</li>
            </ol>
          </div>
        )}

        <form className="qr-form" onSubmit={submit}>
          {manualMode && <div className="form-field">
            <label htmlFor="branch-code">Код отделения</label>
            <div className="code-input-wrap">
              <Keyboard size={20} aria-hidden="true" />
              <input
                id="branch-code"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                pattern="[0-9]{6}"
                maxLength={6}
                placeholder="000000"
                value={code}
                onChange={(event) => changeCode(event.target.value)}
                required
              />
            </div>
            {branchLookup.loading && <p className="field-message hint" role="status">Проверяем код…</p>}
            {codeComplete && branchLookup.error && <p className="field-message error" role="alert">{branchLookup.error}</p>}
            {branch && <p className="field-message success"><Check size={15} aria-hidden="true" /> {branch.address}</p>}
          </div>}

          {!manualMode && branch && <div className="qr-selected-branch"><Check size={16} /><span><small>Ваше отделение</small><strong>{branch.address}</strong></span></div>}

          <ServiceSelect
            services={services.data}
            value={serviceId}
            loading={services.loading}
            error={services.error}
            disabled={!branch}
            onChange={(value) => { setServiceId(value); resetSubmission() }}
          />

          {submitError && <p className="submit-error" role="alert">{submitError}</p>}
          <button className="button primary" type="submit" disabled={!branch || !selectedService || submitting}>
            {submitting ? 'Выдаём талон…' : 'Получить талон'}
            <Check size={20} aria-hidden="true" />
          </button>
        </form>
      </div>
    </section>
  )
}
