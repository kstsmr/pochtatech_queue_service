# Цифровая очередь

MVP для хакатона ПочтаТех: предзапись, QR-талон и живая очередь.
Стек: FastAPI, PostgreSQL, Redis, React/Vite и Docker Compose.

## Быстрый запуск

Нужен Docker Desktop. Из корня репозитория:

```sh
cp .env.example .env
docker compose up --build
```

Сервис API доступен на `http://localhost:8000`.

```sh
curl http://localhost:8000/api/health
curl http://localhost:8000/api/branches
curl http://localhost:8000/api/branches/11111111-1111-1111-1111-111111111111/services
```

Swagger UI: `http://localhost:8000/api/docs`. Остановить сервисы:
`docker compose down`. Данные PostgreSQL и Redis сохраняются в Docker volumes.
Для полного очищения демонстрационных данных выполнить `docker compose down -v`.

`.env` содержит только локальные значения и не попадает в Git. Для общего стенда
измените пароли перед запуском и передавайте их через окружение или менеджер секретов.

## Клиентский интерфейс

```sh
cd innovateQueue
npm ci
npm run dev
```

Проверки frontend:

```sh
npm run lint
npm run build
```

## Реализовано сейчас

- PostgreSQL и Redis с health-check в Docker Compose.
- FastAPI, Alembic-миграция полной схемы и безопасные demo seed-данные.
- `GET /api/health`: проверяет базу и Redis.
- `GET /api/branches` и `GET /api/branches/{branch_id}/services`.
- Статический контракт [openapi.yaml](openapi.yaml) и интерактивная документация.
- Единый формат ошибок: `{ "error_code", "message", "details" }`.
- Структурированные JSON-логи backend.

Предзапись, QR-выдача, ядро выбора следующего талона, WebSocket, уведомления,
операторский и административный интерфейсы пока не реализованы. Форма Vite
не подключена к API до фиксации контрактов соответствующих сценариев.

## Репозиторий

Ветки вливаются в `main` только через Merge Request. CI/CD и runners по правилам
хакатона не используются: перед коммитом проверки запускаются локально.
PAT не хранится в исходниках или remote URL.
