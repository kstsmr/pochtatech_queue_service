import asyncio
import hashlib
import json
from datetime import datetime, time, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import settings
from app.core.priority import load_priority_config
from app.db.session import engine
from app.services.staff import staff_pin_hash

BRANCH_ID = UUID("11111111-1111-1111-1111-111111111111")
SEND_SERVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
RECEIVE_SERVICE_ID = UUID("33333333-3333-3333-3333-333333333333")
PAYMENT_SERVICE_ID = UUID("55555555-5555-5555-5555-555555555555")
BUSINESS_SERVICE_ID = UUID("66666666-6666-6666-6666-666666666666")

BRANCHES = (
    (BRANCH_ID, "101000", "Отделение 101000", "Москва, Мясницкая ул., 26", "Europe/Moscow", 5),
    (UUID("11111111-1111-1111-1111-111111111112"), "119019", "Отделение 119019", "Москва, ул. Арбат, 18", "Europe/Moscow", 4),
    (UUID("11111111-1111-1111-1111-111111111113"), "125009", "Отделение 125009", "Москва, Тверская ул., 7", "Europe/Moscow", 4),
    (UUID("11111111-1111-1111-1111-111111111114"), "190000", "Отделение 190000", "Санкт-Петербург, Почтамтская ул., 9", "Europe/Moscow", 5),
    (UUID("11111111-1111-1111-1111-111111111115"), "420111", "Отделение 420111", "Казань, Кремлёвская ул., 8", "Europe/Moscow", 3),
)
SERVICES = (
    (SEND_SERVICE_ID, "Отправить письмо или посылку", 300),
    (RECEIVE_SERVICE_ID, "Получить отправление", 180),
    (PAYMENT_SERVICE_ID, "Платежи и переводы", 420),
    (BUSINESS_SERVICE_ID, "Услуги для бизнеса", 600),
)
SLOT_TIMES = (time(9, 30), time(10, 15), time(11), time(12, 30), time(14), time(15, 45))


def stable_id(kind: str, *parts: object) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("digital-queue", kind, *(str(part) for part in parts))))


async def seed() -> None:
    priority_config = load_priority_config()
    priority_json = json.dumps(priority_config)
    rule_version = int(priority_config["rule_version"])
    demo_pin = settings.demo_staff_pin.get_secret_value()
    async with engine.begin() as connection:
        for branch_id, postal_code, name, address, timezone_name, window_count in BRANCHES:
            await connection.execute(
                text(
                    """
                    INSERT INTO branches (id, postal_code, name, address, timezone)
                    VALUES (:id, :postal_code, :name, :address, :timezone)
                    ON CONFLICT (id) DO UPDATE SET postal_code = EXCLUDED.postal_code,
                        name = EXCLUDED.name, address = EXCLUDED.address,
                        timezone = EXCLUDED.timezone, active = true
                    """
                ),
                {"id": branch_id, "postal_code": postal_code, "name": name,
                 "address": address, "timezone": timezone_name},
            )
            stored_rule = await connection.scalar(
                text(
                    """
                    SELECT config FROM priority_rules
                    WHERE branch_id = :branch_id AND version = :version
                    """
                ),
                {"branch_id": branch_id, "version": rule_version},
            )
            if stored_rule is not None and stored_rule != priority_config:
                raise RuntimeError(
                    f"Priority rule {rule_version} for branch {branch_id} was changed without a version bump"
                )
            if stored_rule is None:
                await connection.execute(
                    text("UPDATE priority_rules SET active = false WHERE branch_id = :branch_id AND active"),
                    {"branch_id": branch_id},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO priority_rules (branch_id, version, config, actor_id)
                        VALUES (:branch_id, :version, CAST(:config AS jsonb), 'demo-seed')
                        """
                    ),
                    {"branch_id": branch_id, "version": rule_version, "config": priority_json},
                )
            for employee_code, display_name, role in (
                ("operator-1", "Оператор 1", "operator"),
                ("operator-2", "Оператор 2", "operator"),
            ):
                member_id = stable_id("staff", branch_id, employee_code)
                salt = hashlib.sha256(f"demo:{branch_id}:{employee_code}".encode()).digest()[:16]
                await connection.execute(
                    text(
                        """
                        INSERT INTO staff_members
                            (id, branch_id, employee_code, display_name, role, pin_salt, pin_hash)
                        VALUES (:id, :branch_id, :employee_code, :display_name, :role, :pin_salt, :pin_hash)
                        ON CONFLICT (branch_id, (lower(employee_code))) DO UPDATE
                        SET display_name = EXCLUDED.display_name, role = EXCLUDED.role,
                            pin_salt = EXCLUDED.pin_salt, pin_hash = EXCLUDED.pin_hash,
                            active = true, updated_at = clock_timestamp()
                        """
                    ),
                    {"id": member_id, "branch_id": branch_id, "employee_code": employee_code,
                     "display_name": display_name, "role": role, "pin_salt": salt,
                     "pin_hash": staff_pin_hash(demo_pin, salt)},
                )

            for number in range(1, window_count + 1):
                await connection.execute(
                    text(
                        """
                        INSERT INTO windows (id, branch_id, number)
                        VALUES (:id, :branch_id, :number)
                        ON CONFLICT (branch_id, number) DO NOTHING
                        """
                    ),
                    {"id": stable_id("window", branch_id, number),
                     "branch_id": branch_id, "number": number},
                )

        await connection.execute(
            text(
                """
                INSERT INTO services (id, name) VALUES (:id, :name)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true
                """
            ),
            [{"id": service_id, "name": name} for service_id, name, _ in SERVICES],
        )

        for branch_id, _, _, _, timezone_name, _ in BRANCHES:
            await connection.execute(
                text(
                    """
                    INSERT INTO branch_services (branch_id, service_id, average_service_seconds)
                    VALUES (:branch_id, :service_id, :average_service_seconds)
                    ON CONFLICT (branch_id, service_id) DO UPDATE
                    SET average_service_seconds = EXCLUDED.average_service_seconds, active = true
                    """
                ),
                [{"branch_id": branch_id, "service_id": service_id,
                  "average_service_seconds": duration} for service_id, _, duration in SERVICES],
            )
            window_ids = (
                await connection.execute(
                    text("SELECT id FROM windows WHERE branch_id = :branch_id ORDER BY number"),
                    {"branch_id": branch_id},
                )
            ).scalars().all()
            await connection.execute(
                text(
                    """
                    INSERT INTO window_services (branch_id, window_id, service_id)
                    SELECT :branch_id, window_id, service_id
                    FROM unnest(CAST(:window_ids AS uuid[])) AS window_id
                    CROSS JOIN unnest(CAST(:service_ids AS uuid[])) AS service_id
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"branch_id": branch_id, "window_ids": window_ids,
                 "service_ids": [item[0] for item in SERVICES]},
            )

            timezone = ZoneInfo(timezone_name)
            today = datetime.now(timezone).date()
            slots = []
            for day_offset in range(31):
                day = today + timedelta(days=day_offset)
                for service_id, _, _ in SERVICES:
                    for slot_time in SLOT_TIMES:
                        starts_at = datetime.combine(day, slot_time, timezone)
                        slots.append({
                            "id": stable_id("slot", branch_id, service_id, starts_at.isoformat()),
                            "branch_id": branch_id,
                            "service_id": service_id,
                            "starts_at": starts_at,
                            "ends_at": starts_at + timedelta(minutes=30),
                        })
            await connection.execute(
                text(
                    """
                    INSERT INTO appointment_slots
                        (id, branch_id, service_id, starts_at, ends_at, capacity)
                    VALUES (:id, :branch_id, :service_id, :starts_at, :ends_at, 2)
                    ON CONFLICT (branch_id, service_id, starts_at) DO NOTHING
                    """
                ),
                slots,
            )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
