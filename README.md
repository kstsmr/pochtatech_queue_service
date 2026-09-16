# Цифровая очередь

MVP для хакатона ПочтаТех: предзапись, QR-талон и живая очередь.
Стек: FastAPI, PostgreSQL, Redis, React/Vite и Docker Compose.

## Быстрый запуск

Нужен Docker Desktop. Из корня репозитория:

```sh
cp .env.example .env
docker compose up --build
```

Клиентский интерфейс доступен на `http://localhost:3000`, API — на
`http://localhost:8000`.

QR-стенд для демонстрации и печати: `http://localhost:3000/demo/qr`.
Выберите отделение, затем отсканируйте код камерой телефона или нажмите
«Открыть как клиент». После выбора услуги будет создан обычный QR-талон.
Для проверки камерой телефона настройте LAN-адрес по инструкции в
[docs/qr-flow.md](docs/qr-flow.md); по умолчанию сервис не публикуется в сеть.

```sh
curl http://localhost:8000/api/health
curl http://localhost:8000/api/branches
curl http://localhost:8000/api/branches/11111111-1111-1111-1111-111111111111/services
python3 tools/check_api.py
```

Swagger UI: `http://localhost:8000/api/docs`. Остановить сервисы:
`docker compose down`. Данные PostgreSQL и Redis сохраняются в Docker volumes.
Для полного очищения демонстрационных данных выполнить `docker compose down -v`.

`.env` содержит только локальные значения и не попадает в Git. Для общего стенда
измените пароли перед запуском и передавайте их через окружение или менеджер секретов.

## Локальная разработка интерфейса

```sh
cd frontend
npm ci
npm run dev
```

Vite откроет интерфейс на `http://localhost:5173`. По умолчанию он обращается к
локальному API на `http://localhost:8000`; адрес можно изменить через
`frontend/.env` на основе `frontend/.env.example`.

Проверки frontend:

```sh
npm run lint
npm run build
```

## Реализовано сейчас

- PostgreSQL и Redis с health-check в Docker Compose.
- FastAPI, последовательные Alembic-миграции полной схемы и безопасные demo seed-данные.
- `GET /api/health`: проверяет базу и Redis.
- Каталог: отделения, поиск по шестизначному коду, услуги и свободные слоты.
- `POST /api/bookings`: атомарная предварительная запись с резервированием слота.
- `POST /api/queue/join`: выдача QR-талона в живую очередь.
- Серверный SVG QR-код отделения со стабильным deep-link и автоматической
  подстановкой кода после сканирования.
- Тестовый QR-стенд с печатью, загрузкой SVG и имитацией сканирования на одном
  устройстве.
- Получение и отмена талона с `X-Session-Token`; повтор POST защищён
  обязательным `Idempotency-Key`.
- Статический контракт [openapi.yaml](openapi.yaml) и интерактивная документация.
- Единый формат ошибок: `{ "error_code", "message", "details" }`.
- Структурированные JSON-логи backend.

Клиентские маршруты `/`, `/book`, `/qr` и `/ticket` используют REST API.
Идентификатор и непрозрачный токен текущего талона сохраняются на устройстве,
поэтому статус восстанавливается после перезагрузки страницы или временной
потери связи. WebSocket, уведомления, операторский и административный
интерфейсы пока не реализованы. Алгоритм QR-входа описан в
[docs/qr-flow.md](docs/qr-flow.md).

Правила приоритета описаны в [docs/priority-algorithm.md](docs/priority-algorithm.md),
а демонстрационные коэффициенты находятся в `config/priority.yaml`.

## Репозиторий

Ветки вливаются в `main` только через Merge Request. CI/CD и runners по правилам
хакатона не используются: перед коммитом проверки запускаются локально.
PAT не хранится в исходниках или remote URL.
