# Клиент цифровой очереди

React/TypeScript-приложение на Vite. Рабочие маршруты: `/`, `/book`, `/qr` и
`/ticket`. Справочники, свободные слоты, создание и восстановление талона
работают через FastAPI.

```sh
npm ci
npm run dev
```

Перед коммитом:

```sh
npm run lint
npm run build
npm audit
```

`VITE_API_URL` задаёт адрес API для локальной разработки. В Docker-сборке
запросы `/api` проксируются Nginx к сервису `backend`.
