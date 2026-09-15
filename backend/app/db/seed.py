import asyncio
from uuid import UUID

from sqlalchemy import text

from app.db.session import engine

BRANCH_ID = UUID("11111111-1111-1111-1111-111111111111")
SEND_SERVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
RECEIVE_SERVICE_ID = UUID("33333333-3333-3333-3333-333333333333")


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
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
