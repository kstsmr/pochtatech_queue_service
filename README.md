# Цифровая очередь

MVP электронной очереди для отделений Почты России: предварительная запись,
QR-талон в отделении, живая очередь, рабочее место оператора и панель
руководителя.

Стек: FastAPI, PostgreSQL, Redis, React/Vite, Nginx и Docker Compose.

## Запуск за несколько минут

### 1. Что понадобится

- Docker Desktop с поддержкой Docker Compose v2;
- свободные порты `3000` и `8000`;
- терминал, открытый в корне репозитория.

Node.js и Python для обычного запуска не нужны: приложение полностью собирается
и работает в контейнерах.

### 2. Создайте локальное окружение

macOS и Linux:

```sh
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Значения из `.env.example` подходят для локальной демонстрации. После
копирования PIN сотрудников равен `replace-with-a-demo-pin`.

Для общего стенда обязательно замените `POSTGRES_PASSWORD`,
`SESSION_TOKEN_SECRET`, `DEMO_STAFF_PIN` и `DEMO_MOBILE_APP_API_KEY`. При смене
пароля PostgreSQL обновите его также в `DATABASE_URL` и `SYNC_DATABASE_URL`.
Файл `.env` исключён из Git.

### 3. Соберите и запустите сервисы

```sh
docker compose up -d --build
```

При первом запуске Docker загрузит базовые образы и соберёт frontend и backend.
Alembic-миграции, демонстрационные отделения, услуги, окна и сотрудники создаются
автоматически. Существующие данные при последующих запусках сохраняются.

### 4. Дождитесь готовности

```sh
docker compose ps
curl -fsS http://localhost:8000/api/health
```

У `db`, `redis`, `backend` и `frontend` должен появиться статус `healthy`, у
`notification-worker` — `Up`. Health endpoint должен вернуть статус `ok`.

### 5. Откройте приложение

| Раздел | Адрес |
|---|---|
| Клиентский интерфейс | <http://localhost:3000> |
| Предварительная запись | <http://localhost:3000/book> |
| Вход по коду отделения | <http://localhost:3000/qr> |
| QR-стенд для демонстрации | <http://localhost:3000/demo/qr> |
| Киоск-режим | <http://localhost:3000/kiosk> |
| Вход сотрудников | <http://localhost:3000/staff> |
| Панель руководителя | <http://localhost:3000/manager> |
| Swagger UI | <http://localhost:8000/api/docs> |

Frontend проксирует REST API и WebSocket в backend, поэтому для обычной работы
достаточно открыть порт `3000`.

## Демонстрационные учётные записи

На странице `/staff` выберите любое отделение и используйте один из кодов:

| Роль | Код сотрудника | PIN после копирования `.env.example` |
|---|---|---|
| Оператор | `operator-1` | `replace-with-a-demo-pin` |
| Оператор | `operator-2` | `replace-with-a-demo-pin` |
| Руководитель | `manager-1` | `replace-with-a-demo-pin` |

После входа сервис сам откроет интерфейс, соответствующий роли. Отдельная
регистрация сотрудников в демонстрационной версии не требуется.

## Быстрая демонстрация сценариев

### Предварительная запись

1. Откройте `/book`.
2. Выберите отделение, услугу, дату и свободное время.
3. Создайте талон и откройте страницу его статуса.
4. Перезагрузите страницу: талон восстановится из локальной сессии.

### QR-талон в отделении

1. Откройте `/demo/qr` и выберите отделение.
2. Нажмите «Открыть как клиент» или отсканируйте QR-код телефоном.
3. Выберите услугу и получите электронный талон.
4. Войдите как оператор, откройте окно с этой услугой и вызовите клиента.
5. Номер окна появится на странице талона через WebSocket.

### Руководитель отделения

1. Войдите на `/staff` с кодом `manager-1`.
2. Проверьте текущую очередь, загрузку окон и показатели ожидания.
3. Настройте услуги окон или правила приоритета.
4. Просмотрите отклонения, незавершённые талоны и зарегистрированные проблемы.

## Проверка QR с телефона

Компьютер и телефон должны находиться в одной доверенной Wi-Fi-сети. Узнайте
LAN-IP компьютера и измените `.env`, например:

```dotenv
PUBLIC_CLIENT_URL=http://192.168.1.50:3000
FRONTEND_BIND_HOST=0.0.0.0
```

Затем пересоздайте frontend и backend:

```sh
docker compose up -d --build frontend backend
```

Откройте на компьютере `http://localhost:3000/demo/qr`. Backend отдельно в сеть
публиковать не требуется: `/api` и WebSocket проксируются через Nginx. После
демонстрации верните `FRONTEND_BIND_HOST=127.0.0.1`. Подробности и модель
безопасности описаны в [docs/qr-flow.md](docs/qr-flow.md).

## Управление сервисами

Повторный запуск без пересборки:

```sh
docker compose up -d
```

Пересборка после изменения исходного кода:

```sh
docker compose up -d --build
```

Просмотр логов:

```sh
docker compose logs -f backend notification-worker
```

Остановка с сохранением данных:

```sh
docker compose down
```

Полный сброс демонстрационной базы и Redis:

```sh
docker compose down -v
docker compose up -d --build
```

Команда `down -v` безвозвратно удаляет локальные Docker volumes проекта.

## Если сервис не запускается

1. Выполните `docker compose ps` и дождитесь завершения health-check.
2. Посмотрите причину через `docker compose logs --tail=200 backend db redis`.
3. Проверьте занятость портов `3000` и `8000` другими программами.
4. Убедитесь, что в `.env` совпадают `POSTGRES_PASSWORD` и пароли внутри обеих
   строк подключения к БД.
5. Если пароль менялся после первого запуска, старый PostgreSQL volume продолжит
   использовать прежние учётные данные. Для пустой локальной среды выполните
   `docker compose down -v` и запустите проект заново.

Проверить только backend можно командой:

```sh
curl -i http://localhost:8000/api/health
```

## Автоматические проверки

Сначала запустите Docker Compose. Затем из корня репозитория:

```sh
python3 tools/check_api.py
python3 tools/check_staff.py
python3 tools/check_manager.py
node tools/check_qr.mjs
python3 tools/check_integration.py
python3 tools/check_service_capacity.py
python3 tools/check_seed_persistence.py
python3 tools/check_restart.py
python3 tools/check_security.py
python3 -m unittest discover -s tests -v
```

Для `check_qr.mjs` нужен Node.js 22+, для Python-проверок — Python 3.10+
без дополнительных пакетов. `check_restart.py` действительно перезапускает
backend-контейнер и проверяет восстановление активного талона.

Проверки frontend:

```sh
cd frontend
npm ci
npm run lint
npm run build
```

## Локальная разработка frontend

При запущенном backend можно поднять Vite отдельно:

```sh
cd frontend
cp .env.example .env
npm ci
npm run dev
```

Интерфейс откроется на `http://localhost:5173` и будет обращаться к API по
адресу из `frontend/.env`.

## Возможности MVP

- атомарная предварительная запись с учётом общего числа и специализации окон;
- стабильный QR deep-link без персональных данных и серверная SVG-генерация;
- живая очередь и конкурентно безопасный вызов без двойного назначения;
- возврат, перенаправление, повторный вызов, неявка и завершение обслуживания;
- настраиваемые и версионируемые правила приоритета с защитой от долгого ожидания;
- клиентский статус по WebSocket с REST fallback, ETA и номером окна;
- durable outbox уведомлений с таймаутом и повторной доставкой;
- панель руководителя с очередью, метриками, окнами, услугами и отклонениями;
- PostgreSQL persistence, журнал событий, health-check и структурированные логи;
- OpenAPI-контракт: [openapi.yaml](openapi.yaml).

## Документация

- [Матрица покрытия ТЗ](docs/acceptance-matrix.md)
- [Алгоритм приоритета](docs/priority-algorithm.md)
- [Рабочее место оператора](docs/staff-workplace.md)
- [Панель руководителя](docs/manager-workplace.md)
- [QR-сценарий](docs/qr-flow.md)
- [Расписание и вместимость](docs/appointment-capacity.md)
- [Уведомления](docs/notifications.md)
- [Безопасность и проверка защиты](docs/security.md)
- [Архитектура и масштабирование](docs/architecture.md)
- [Целевой пользовательский поток](docs/target-flow.md)

## Репозиторий

Ветка `main` защищена. Изменения отправляются в feature-ветку и вливаются через
Merge Request. CI/CD и GitLab runners по условиям хакатона не используются,
поэтому проверки выполняются локально. PAT и `.env` не должны попадать в Git.
