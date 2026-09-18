import { ArrowLeft, Download, ExternalLink, Maximize, Printer, QrCode, TriangleAlert, Wifi } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiAssetUrl } from '../api/client'
import { BranchSelect } from '../components/BranchSelect'
import { useBranches, useBranchQr } from '../hooks/useCatalog'

export function QrStandPage({ kiosk = false }: { kiosk?: boolean }) {
  const branches = useBranches()
  const [branchId, setBranchId] = useState('')
  const [publicOrigin, setPublicOrigin] = useState(() => window.location.origin)
  const [originDraft, setOriginDraft] = useState(() => window.location.origin)
  const [originError, setOriginError] = useState<string | null>(null)
  const selectedBranch = branches.data.find((branch) => branch.id === branchId)
  const qr = useBranchQr(branchId, publicOrigin)
  const targetHost = qr.data ? new URL(qr.data.join_url).hostname : ''
  const phoneReady = Boolean(targetHost && !['localhost', '127.0.0.1', '::1'].includes(targetHost))

  function applyOrigin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      const parsed = new URL(originDraft)
      if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
        throw new Error()
      }
      setPublicOrigin(parsed.origin)
      setOriginDraft(parsed.origin)
      setOriginError(null)
    } catch {
      setOriginError('Укажите адрес вида http://192.168.1.50:3000 без пути')
    }
  }

  return (
    <section className={`flow-page qr-stand-page ${kiosk ? 'kiosk-page' : ''}`}>
      <div className="flow-heading no-print">
        <Link className="back-link" to="/"><ArrowLeft size={18} aria-hidden="true" /> Назад</Link>
        <p className="route-kicker"><span aria-hidden="true">QR</span> {kiosk ? 'Киоск' : 'Стенд отделения'}</p>
        <h1>{kiosk ? 'Экран электронной очереди' : 'QR-код для живой очереди'}</h1>
        <p>{kiosk ? 'Выберите отделение и разверните экран для клиентской зоны.' : 'Выберите отделение и распечатайте готовый код для клиентской зоны.'}</p>
      </div>

      <div className="qr-stand-layout">
        <div className="qr-stand-controls no-print">
          <BranchSelect
            branches={branches.data}
            value={branchId}
            loading={branches.loading}
            error={branches.error}
            onChange={setBranchId}
            search={branches.search}
            onSearch={branches.setSearch}
            hint="Для каждого отделения формируется постоянная ссылка"
          />
          <form className="qr-origin-form" onSubmit={applyOrigin}>
            <label htmlFor="public-origin">Адрес, который откроется на телефоне</label>
            <div><Wifi size={18} aria-hidden="true" /><input id="public-origin" type="url" value={originDraft} onChange={(event) => setOriginDraft(event.target.value)} spellCheck="false" /><button className="button secondary inline-button" type="submit">Применить</button></div>
            {originError && <p className="field-message error" role="alert">{originError}</p>}
            {qr.data && !phoneReady && <p className="qr-phone-warning"><TriangleAlert size={16} /> Этот QR ведёт на localhost и не откроется на телефоне. Укажите сетевой адрес компьютера.</p>}
            {qr.data && phoneReady && <p className="field-message success"><Wifi size={15} /> QR готов для телефона: {targetHost}</p>}
          </form>
          {qr.error && <p className="submit-error" role="alert">{qr.error}</p>}
          {qr.data && (
            <div className="qr-stand-actions">
              <a className="button primary" href={qr.data.join_url}>
                Открыть как клиент <ExternalLink size={19} aria-hidden="true" />
              </a>
              <button className="button secondary inline-button" type="button" onClick={() => window.print()}>
                <Printer size={18} aria-hidden="true" /> Печать
              </button>
              {kiosk && <button className="button secondary inline-button" type="button" onClick={() => void document.documentElement.requestFullscreen()}><Maximize size={18} aria-hidden="true" /> На весь экран</button>}
              <a className="button secondary inline-button" href={apiAssetUrl(qr.data.qr_svg_path)} download>
                <Download size={18} aria-hidden="true" /> SVG
              </a>
            </div>
          )}
        </div>

        <article className={`qr-poster ${qr.loading ? 'loading' : ''}`} aria-live="polite">
          {qr.data && selectedBranch ? (
            <>
              <div className="qr-poster-brand"><span>О</span><strong>Электронная очередь</strong></div>
              <img src={apiAssetUrl(qr.data.qr_svg_path)} alt={`QR-код отделения ${qr.data.postal_code}`} />
              <div className="qr-poster-copy">
                <p>Наведите камеру телефона</p>
                <h2>Получите талон в электронную очередь</h2>
                <strong>{selectedBranch.address}</strong>
              </div>
              <div className="qr-poster-code"><span>Код отделения</span>{qr.data.postal_code}</div>
            </>
          ) : (
            <div className="qr-poster-empty">
              <QrCode size={64} aria-hidden="true" />
              <strong>{qr.loading ? 'Создаём QR-код…' : 'Выберите отделение'}</strong>
            </div>
          )}
        </article>
      </div>
    </section>
  )
}
