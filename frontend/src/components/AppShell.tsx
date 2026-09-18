import { Accessibility, CalendarDays, Home, QrCode, Ticket, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Главная', icon: Home, end: true },
  { to: '/book', label: 'Запись', icon: CalendarDays },
  { to: '/qr', label: 'QR-код', icon: QrCode },
  { to: '/ticket', label: 'Мой талон', icon: Ticket },
]

export function AppShell() {
  const location = useLocation()
  const [accessible, setAccessible] = useState(() => localStorage.getItem('digital-queue.accessible') === 'true')

  useEffect(() => {
    document.documentElement.dataset.accessible = String(accessible)
    localStorage.setItem('digital-queue.accessible', String(accessible))
  }, [accessible])

  return (
    <div className="site-shell">
      <a className="skip-link" href="#content">К содержанию</a>
      <header className="site-header">
        <NavLink className="brand" to="/" aria-label="Очередь — главная">
          <span className="brand-stamp" aria-hidden="true">О</span>
          <span className="brand-text">Очередь</span>
          <span className="brand-caption">сервис визита</span>
        </NavLink>

        <nav className="desktop-nav" aria-label="Основная навигация">
          {navItems.slice(1).map(({ to, label }) => (
            <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="header-actions">
          <button
            className="accessibility-button"
            type="button"
            aria-pressed={accessible}
            aria-label={accessible ? 'Выключить крупный текст' : 'Включить крупный текст'}
            title={accessible ? 'Выключить крупный текст' : 'Включить крупный текст'}
            onClick={() => setAccessible((value) => !value)}
          >
            <Accessibility size={18} aria-hidden="true" />
            <span>Крупный текст</span>
          </button>
          <NavLink className="staff-button" to="/staff">
            <UserRound size={18} aria-hidden="true" />
            <span>Сотрудникам</span>
          </NavLink>
        </div>
      </header>

      <main id="content" className="page-frame" key={location.pathname}>
        <Outlet />
      </main>

      <nav className="mobile-nav" aria-label="Мобильная навигация">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? 'mobile-link active' : 'mobile-link'}>
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
