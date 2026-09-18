import { ArrowRight, CalendarClock, Clock3, QrCode, Radio, TicketCheck } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
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
          <p className="route-kicker"><span aria-hidden="true">01</span> Онлайн-запись</p>
          <h1 id="home-title">Выберите удобное время</h1>
          <p className="home-lead">
            Запишитесь в нужное отделение или получите электронный талон, если уже пришли.
          </p>

          <div className="start-panel">
            <div className="start-panel-heading">
              <span>Запись в отделение</span>
              <strong>Сначала выберите адрес</strong>
            </div>
            <BranchSelect
              branches={branches.data}
              value={branchId}
              loading={branches.loading}
              error={branches.error}
              onChange={selectBranch}
              search={branches.search}
              onSearch={branches.setSearch}
              hint="Затем выберете услугу и свободное время"
            />
            <button className="button primary" type="button" disabled={!branchId} onClick={startBooking}>
              Выбрать услугу и время
              <ArrowRight size={20} aria-hidden="true" />
            </button>
            <Link className="text-action" to="/qr">
              Я уже в отделении — получить талон
              <QrCode size={18} aria-hidden="true" />
            </Link>
            <Link className="text-action demo-action" to="/demo/qr">
              QR-стенд для проверки
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          </div>

          <div className="service-note" aria-live="polite">
            <span className={branches.error ? 'status-dot offline' : 'status-dot'} aria-hidden="true" />
            {branches.loading && 'Загружаем список отделений'}
            {!branches.loading && branches.error && 'Не удалось получить список отделений'}
            {!branches.loading && !branches.error && selectedBranch && `Выбрано: ${selectedBranch.address}`}
            {!branches.loading && !branches.error && !selectedBranch && `Доступно отделений: ${branches.data.length}`}
          </div>
        </div>

        <div className="branch-board" aria-label="Пример табло электронной очереди">
          <div className="branch-board-header">
            <div>
              <span>Табло отделения</span>
              <strong>{selectedBranch?.address ?? 'Москва, Мясницкая ул., 26'}</strong>
            </div>
            <span className="board-live"><i aria-hidden="true" /> Онлайн</span>
          </div>
          <div className="branch-board-call">
            <div><span>Вызван талон</span><strong>А 024</strong></div>
            <div className="board-window"><small>Окно</small><b>03</b></div>
          </div>
          <div className="branch-board-list" aria-hidden="true">
            <div className="current"><Radio size={15} /><strong>А 024</strong><span>Получение</span><b>Окно 03</b></div>
            <div><Clock3 size={15} /><strong>Б 017</strong><span>Отправка</span><b>Ожидает</b></div>
            <div><Clock3 size={15} /><strong>А 025</strong><span>Получение</span><b>Ожидает</b></div>
          </div>
          <div className="branch-board-footer">
            <span><small>Среднее ожидание</small><strong>8 минут</strong></span>
            <span><small>Сейчас работают</small><strong>4 окна</strong></span>
          </div>
        </div>
      </section>

      <section className="route-board" aria-label="Варианты посещения">
        <div className="route-line" aria-hidden="true"><span /><span /><span /></div>
        <Link to="/book" className="route-item">
          <span className="route-icon blue"><CalendarClock /></span>
          <span><strong>Записаться</strong><small>Выбрать услугу и время</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
        <Link to="/qr" className="route-item">
          <span className="route-icon mint"><QrCode /></span>
          <span><strong>Получить талон</strong><small>По QR-коду в отделении</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
        <Link to="/ticket" className="route-item">
          <span className="route-icon red"><TicketCheck /></span>
          <span><strong>Статус талона</strong><small>Очередь и номер окна</small></span>
          <ArrowRight className="route-arrow" aria-hidden="true" />
        </Link>
      </section>
    </>
  )
}
