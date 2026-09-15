import './App.css'

const ArrowRightIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
)

const TicketIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a3 3 0 0 0 0 6v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a3 3 0 0 0 0-6V7Z" />
    <path d="M12 8v1M12 12v1M12 16v1" />
  </svg>
)

function App() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Очередь — на главную">
          <span className="brand-mark" aria-hidden="true">О</span>
          <span>Очередь</span>
        </a>
        <button className="ticket-link" type="button">
          <TicketIcon />
          Мой талон
        </button>
      </header>

      <section className="hero-section" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Электронная очередь</p>
          <h1>Решайте дела на почте без лишнего ожидания</h1>
          <p className="lead">
            Запишитесь заранее или получите электронный талон в отделении.
            Мы подскажем, когда подойдёт ваша очередь.
          </p>
        </div>

        <form className="queue-form" onSubmit={(event) => event.preventDefault()}>
          <div className="field-group">
            <label htmlFor="branch">Отделение</label>
            <select id="branch" defaultValue="">
              <option value="" disabled>Выберите отделение</option>
              <option value="101000">101000, Москва, Мясницкая ул., 26</option>
              <option value="119019">119019, Москва, Новый Арбат, 7А</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="service">Услуга</label>
            <select id="service" defaultValue="">
              <option value="" disabled>Что хотите сделать?</option>
              <option value="send">Отправить письмо или посылку</option>
              <option value="receive">Получить отправление</option>
              <option value="payment">Платежи и переводы</option>
            </select>
          </div>

          <button className="primary-button" type="submit">
            Выбрать время
            <ArrowRightIcon />
          </button>
        </form>
      </section>

      <section className="entry-options" aria-label="Способы встать в очередь">
        <article>
          <span className="option-number">01</span>
          <div>
            <h2>Запись ко времени</h2>
            <p>Выберите удобный интервал и приходите к назначенному часу.</p>
          </div>
        </article>
        <article>
          <span className="option-number">02</span>
          <div>
            <h2>Талон по QR-коду</h2>
            <p>Отсканируйте код в отделении со своего телефона.</p>
          </div>
        </article>
        <article>
          <span className="option-number">03</span>
          <div>
            <h2>Статус онлайн</h2>
            <p>Следите за очередью и номером окна на экране.</p>
          </div>
        </article>
      </section>
    </main>
  )
}

export default App
