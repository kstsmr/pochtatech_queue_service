import { ArrowRight, CalendarClock, QrCode, TicketCheck } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import postOfficeImage from '../assets/post-office-interior.jpg'
import { BranchSelect } from '../components/BranchSelect'
import { useBranches } from '../hooks/useCatalog'
import { useState } from 'react'

const LAST_BRANCH_KEY = 'digital-queue.last-branch.v1'

export function HomePage() {
  const branches = useBranches()
  const [branchId, setBranchId] = useState(() => localStorage.getItem(LAST_BRANCH_KEY) ?? '')
  const navigate = useNavigate()
  const selectedBranch = branches.data.find((branch) => branch.id === branchId)

  function selectBranch(value: string) {
    setBranchId(value)
    if (value) localStorage.setItem(LAST_BRANCH_KEY, value)
  }

  function startBooking() {
    if (!branchId) return
    navigate(`/book?branch=${encodeURIComponent(branchId)}`)
  }

  return (
    <>
      <section className="home-grid" aria-labelledby="home-title">
        <div className="home-intro">
          <p className="route-kicker"><span aria-hidden="true">01</span> Начало визита</p>
          <h1 id="home-title">Почта по вашему времени</h1>
          <p className="home-lead">
            Выберите отделение сейчас. Дальше покажем доступные услуги и сохраним маршрут визита.
          </p>

          <div className="start-panel">
            <div className="start-panel-heading">
              <span>Предварительная запись</span>
              <strong>Начните с адреса</strong>
            </div>
            <BranchSelect
              branches={branches.data}
              value={branchId}
              loading={branches.loading}
              error={branches.error}
              onChange={selectBranch}
              hint="После выбора покажем услуги и свободное время"
            />
            <button className="button primary" type="button" disabled={!branchId} onClick={startBooking}>
              Записаться ко времени
              <ArrowRight size={20} aria-hidden="true" />
            </button>
            <Link className="text-action" to="/qr">
              Я уже в отделении — ввести QR-код
              <QrCode size={18} aria-hidden="true" />
            </Link>
            <Link className="text-action demo-action" to="/demo/qr">
              Открыть тестовый QR-стенд
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          </div>

          <div className="service-note" aria-live="polite">
            <span className={branches.error ? 'status-dot offline' : 'status-dot'} aria-hidden="true" />
            {branches.loading && 'Проверяем доступные отделения'}
            {!branches.loading && branches.error && 'Сервер очереди временно недоступен'}
            {!branches.loading && !branches.error && selectedBranch && `${selectedBranch.name} выбрано`}
            {!branches.loading && !branches.error && !selectedBranch && `${branches.data.length} отделение доступно для демо`}
          </div>
        </div>

        <figure className="branch-figure">
          <img src={postOfficeImage} alt="Светлый зал современного почтового отделения" />
          <figcaption>
            <span>Отделение 101000</span>
            <strong>Мясницкая, 26</strong>
          </figcaption>
          <div className="figure-stamp" aria-hidden="true">10:24</div>
        </figure>
      </section>

      <section className="route-board" aria-label="Варианты посещения">
        <div className="route-line" aria-hidden="true"><span /><span /><span /></div>
        <Link to="/book" className="route-item">
          <span className="route-icon blue"><CalendarClock /></span>
          <span><strong>Запись</strong><small>Выбрать дату и время</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
        <Link to="/qr" className="route-item">
          <span className="route-icon mint"><QrCode /></span>
          <span><strong>В отделении</strong><small>Ввести код с плаката</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
        <Link to="/ticket" className="route-item">
          <span className="route-icon red"><TicketCheck /></span>
          <span><strong>Мой визит</strong><small>Проверить статус талона</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
      </section>
    </>
  )
}
