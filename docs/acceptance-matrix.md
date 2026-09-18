# Матрица покрытия ТЗ

| Требование | Реализация | Проверка |
|---|---|---|
| Предварительная запись | `/book`, `POST /api/bookings`, demo mobile adapter | `tools/check_api.py`, `tools/check_integration.py` |
| QR-талон в ОПС | стабильный deep-link, SVG, `/qr`, атомарный `queue/join` | `tools/check_qr.mjs` |
| Живая очередь | добавление оператором с идемпотентностью | `tools/check_staff.py` |
| Статус, прогноз и окно | приватные REST/WS, позиция и ETA | `tools/check_qr.mjs` |
| Отмена и восстановление | токен хранится на устройстве, повторный GET/POST | `tools/check_api.py` |
| Уведомление | browser channel, серверное напоминание по времени и durable demo outbox | `tests/test_notification_adapter.py`, `tools/check_integration.py` |
| Окно и услуги оператора | open/close/draining, совместимые услуги | `tools/check_staff.py` |
| Вызов без дубля | row lock, `SKIP LOCKED`, уникальный индекс | конкурентный сценарий `check_staff.py` |
| Возврат и перенаправление | сохранение возраста, услуга/целевое окно | `tools/check_staff.py` |
| Фиксация проблемы | технический/операционный incident | `tools/check_staff.py` |
| Управление руководителя | услуги, окна, versioned priority | `tools/check_manager.py` |
| Аналитика и отклонения | ожидание, загрузка, обслужено, incidents | `tools/check_manager.py` |
| Перезапуск | PostgreSQL volumes, восстановление талона, seed не перетирает настройки | `tools/check_restart.py`, `tools/check_seed_persistence.py` |
| Недоступные уведомления | timeout, retry, terminal failure | unit-тест и режим `unavailable` |
| Конкурентная выдача | advisory lock, idempotency и capacity совместимых окон | `tools/check_api.py`, `tools/check_service_capacity.py` |
| OpenAPI и ошибки | `/api/openapi.json`, `openapi.yaml`, единый payload | contract/smoke checks |
| Логи и health | JSON logs, DB/Redis health | Compose healthchecks |
| 40 000 отделений | региональные ячейки и shard по `branch_id` | расчётный проект в `docs/architecture.md` |

Результаты smoke-тестов относятся к локальному MVP. Расчёт масштабирования,
полностью автономный edge-режим и реальные интеграции не выдаются за фактически
нагрузочно проверенные возможности.
