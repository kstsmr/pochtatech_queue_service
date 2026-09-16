import { ArrowLeft, Download, ExternalLink, Printer, QrCode } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiAssetUrl } from '../api/client'
import { BranchSelect } from '../components/BranchSelect'
import { useBranches, useBranchQr } from '../hooks/useCatalog'

export function QrStandPage() {
  const branches = useBranches()
  const [branchId, setBranchId] = useState('')
  const selectedBranch = branches.data.find((branch) => branch.id === branchId)
  const qr = useBranchQr(branchId)

  return (
    <section className="flow-page qr-stand-page">
      <div className="flow-heading no-print">
        <Link className="back-link" to="/"><ArrowLeft size={18} aria-hidden="true" /> Назад</Link>
        <p className="route-kicker"><span aria-hidden="true">QR</span> Стенд отделения</p>
        <h1>QR-код для живой очереди</h1>
        <p>Выберите отделение и распечатайте готовый код для клиентской зоны.</p>
      </div>

      <div className="qr-stand-layout">
        <div className="qr-stand-controls no-print">
          <BranchSelect
            branches={branches.data}
            value={branchId}
            loading={branches.loading}
            error={branches.error}
            onChange={setBranchId}
            hint="Для каждого отделения формируется постоянная ссылка"
          />
          {qr.error && <p className="submit-error" role="alert">{qr.error}</p>}
          {qr.data && (
            <div className="qr-stand-actions">
              <a className="button primary" href={qr.data.join_url}>
                Открыть как клиент <ExternalLink size={19} aria-hidden="true" />
              </a>
              <button className="button secondary inline-button" type="button" onClick={() => window.print()}>
                <Printer size={18} aria-hidden="true" /> Печать
              </button>
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
                <h2>Получите талон без терминала</h2>
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
