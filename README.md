# Цифровая очередь

MVP для хакатона ПочтаТех: предзапись, QR-талон и живая очередь.
Стек согласован: FastAPI, PostgreSQL, React/Vite, Docker Compose.

## Текущее состояние

Есть frontend-прототип в innovateQueue/ и проектирование первых трёх задач тимлида.
Backend, миграции Alembic, OpenAPI и Docker Compose ещё не реализованы.
Форма на стартовом экране не создаёт реальные записи.

## Запуск frontend

Из корня репозитория, с установленными Node.js/npm:

```sh
cd innovateQueue
npm ci
npm run dev
```

Откройте адрес, который напечатает Vite. Проверки frontend:

```sh
npm run lint
npm run build
```

## Модель данных и правила

- [ER-схема и ответственность таблиц](docs/data-model.md)
- [SQL-спецификация, ещё не миграция](docs/schema.sql)
- [Поля талона и переходы состояний](docs/ticket-lifecycle.md)
- [Алгоритм приоритета и примеры](docs/priority-algorithm.md)
- [Конфигурация приоритетов](config/priority.yaml)
- [Фактические проверки и следующие этапы](docs/task-report.md)

Проверки из корня репозитория, Python 3.10+ без сторонних зависимостей:

```sh
python3 tools/check_priority.py
python3 -m unittest discover -s tests -v
```

## Работа команды

Изменения отправляем отдельной веткой и через Merge Request в main.
Перед коммитом проверяем git status, добавляем только файлы своей задачи.
CI/CD и runners не используем: проверки запускаются локально.
PAT не хранится в исходниках или remote URL; аутентификация Git по HTTPS.
Настройки окружения и пароли хранятся вне исходного кода.

Ближайший этап: OpenAPI, backend-каркас и Alembic/Docker Compose с проверкой
схемы на PostgreSQL. Правила v1 служат основой реализации; изменения контракта
согласуются между backend, frontend и Infra до интеграции.
