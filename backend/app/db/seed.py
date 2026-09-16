import asyncio
import json
from datetime import datetime, time, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db.session import engine
from app.core.priority import load_priority_config

BRANCH_ID = UUID("11111111-1111-1111-1111-111111111111")
SEND_SERVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
RECEIVE_SERVICE_ID = UUID("33333333-3333-3333-3333-333333333333")
SLOT_TIMES = (time(9, 30), time(10, 15), time(11), time(12, 30), time(14), time(15, 45))


async def seed() -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO branches (id, postal_code, name, address, timezone)
                VALUES (:id, '101000', 'Отделение 101000', 'Москва, Мясницкая ул., 26', 'Europe/Moscow')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": BRANCH_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO services (id, name) VALUES
                  (:send_id, 'Отправить письмо или посылку'),
                  (:receive_id, 'Получить отправление')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"send_id": SEND_SERVICE_ID, "receive_id": RECEIVE_SERVICE_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO branch_services (branch_id, service_id, average_service_seconds) VALUES
                  (:branch_id, :send_id, 300),
                  (:branch_id, :receive_id, 180)
                ON CONFLICT (branch_id, service_id) DO NOTHING
                """
            ),
            {"branch_id": BRANCH_ID, "send_id": SEND_SERVICE_ID, "receive_id": RECEIVE_SERVICE_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO priority_rules (branch_id, version, config, actor_id)
                VALUES (:branch_id, 1, CAST(:config AS jsonb), 'demo-seed')
                ON CONFLICT (branch_id, version) DO UPDATE SET config = EXCLUDED.config
                """
            ),
            {"branch_id": BRANCH_ID, "config": json.dumps(load_priority_config())},
        )

        timezone = ZoneInfo("Europe/Moscow")
        today = datetime.now(timezone).date()
        slots = []
        for day_offset in range(31):
            day = today + timedelta(days=day_offset)
            for service_id in (SEND_SERVICE_ID, RECEIVE_SERVICE_ID):
                for slot_time in SLOT_TIMES:
                    starts_at = datetime.combine(day, slot_time, timezone)
                    ends_at = starts_at + timedelta(minutes=30)
                    slot_id = uuid5(NAMESPACE_URL, f"queue:{BRANCH_ID}:{service_id}:{starts_at.isoformat()}")
                    slots.append(
                        {
                            "id": slot_id,
                            "branch_id": BRANCH_ID,
                            "service_id": service_id,
                            "starts_at": starts_at,
                            "ends_at": ends_at,
                        }
                    )
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
