import asyncio
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import close_engine, engine
from app.services.notification_adapter import (
    DemoNotificationAdapter,
    NotificationAdapter,
    deliver_with_timeout,
    retry_delay_seconds,
)

logger = logging.getLogger(__name__)


async def enqueue_ticket_notification(
    connection: AsyncConnection,
    *,
    branch_id: UUID,
    event_id: UUID,
    ticket_id: UUID,
    channel: str,
    kind: str,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    ticket = (
        await connection.execute(
            text(
                """
                SELECT t.ticket_number, t.status, t.session_id, w.number AS window_number
                FROM tickets t
                LEFT JOIN windows w ON w.id = t.window_id AND w.branch_id = t.branch_id
                WHERE t.id = :ticket_id AND t.branch_id = :branch_id
                """
            ),
            {"ticket_id": ticket_id, "branch_id": branch_id},
        )
    ).mappings().one_or_none()
    if ticket is None or ticket["session_id"] is None:
        return
    payload = {
        "kind": kind,
        "ticket_id": str(ticket_id),
        "ticket_number": ticket["ticket_number"],
        "status": ticket["status"],
        "window_number": ticket["window_number"],
        **(extra_payload or {}),
    }
    await connection.execute(
        text(
            """
            INSERT INTO notification_log (id, branch_id, event_id, channel, payload)
            VALUES (:id, :branch_id, :event_id, :channel, CAST(:payload AS jsonb))
            ON CONFLICT (event_id, channel) DO NOTHING
            """
        ),
        {
            "id": uuid4(),
            "branch_id": branch_id,
            "event_id": event_id,
            "channel": channel,
            "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        },
    )


async def _claim_notification() -> dict[str, Any] | None:
    lease_seconds = max(settings.notification_delivery_timeout_seconds * 2, 5)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE notification_log
                SET status = 'retry', locked_until = NULL, next_attempt_at = clock_timestamp(),
                    last_error = COALESCE(last_error, 'delivery lease expired')
                WHERE status = 'processing' AND locked_until <= clock_timestamp()
                """
            )
        )
        row = (
            await connection.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT id FROM notification_log
                        WHERE status IN ('pending', 'retry')
                          AND next_attempt_at <= clock_timestamp()
                        ORDER BY next_attempt_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE notification_log n
                    SET status = 'processing', attempts = attempts + 1,
                        locked_until = clock_timestamp() + make_interval(secs => :lease_seconds)
                    FROM candidate
                    WHERE n.id = candidate.id
                    RETURNING n.id, n.payload, n.attempts
                    """
                ),
                {"lease_seconds": lease_seconds},
            )
        ).mappings().one_or_none()
    return dict(row) if row else None


async def enqueue_due_appointment_reminders() -> int:
    """Queue one reminder when a prebooking enters its configured early window."""
    async with engine.begin() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    INSERT INTO notification_log (id, branch_id, event_id, channel, payload)
                    SELECT gen_random_uuid(), t.branch_id, latest_event.id,
                           'demo_appointment_approaching',
                           jsonb_build_object(
                               'kind', 'appointment_approaching',
                               'ticket_id', t.id::text,
                               'ticket_number', t.ticket_number,
                               'status', t.status,
                               'scheduled_time', t.scheduled_time
                           )
                    FROM tickets t
                    JOIN LATERAL (
                        SELECT e.id FROM ticket_events e
                        WHERE e.branch_id = t.branch_id AND e.ticket_id = t.id
                        ORDER BY e.ticket_version DESC LIMIT 1
                    ) latest_event ON true
                    WHERE t.source = 'prebooking' AND t.status = 'booked'
                      AND t.session_id IS NOT NULL
                      AND t.eligible_at <= clock_timestamp()
                    ON CONFLICT (event_id, channel) DO NOTHING
                    RETURNING id
                    """
                )
            )
        ).scalars().all()
    if rows:
        logger.info("appointment_reminders_enqueued", extra={"count": len(rows)})
    return len(rows)


async def _mark_sent(notification_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE notification_log
                SET status = 'sent', locked_until = NULL, delivered_at = clock_timestamp(),
                    last_error = NULL
                WHERE id = :id AND status = 'processing'
                """
            ),
            {"id": notification_id},
        )


async def _mark_failed(notification_id: UUID, attempts: int, error: Exception) -> None:
    terminal = attempts >= settings.notification_max_attempts
    delay = retry_delay_seconds(attempts)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE notification_log
                SET status = :status, locked_until = NULL,
                    next_attempt_at = clock_timestamp() + make_interval(secs => :delay),
                    last_error = :last_error
                WHERE id = :id AND status = 'processing'
                """
            ),
            {
                "id": notification_id,
                "status": "failed" if terminal else "retry",
                "delay": delay,
                "last_error": str(error)[:1000],
            },
        )
    logger.warning(
        "notification_delivery_failed",
        extra={
            "notification_id": str(notification_id),
            "attempt": attempts,
            "terminal": terminal,
            "error_type": type(error).__name__,
        },
    )


async def process_one(adapter: NotificationAdapter) -> bool:
    notification = await _claim_notification()
    if notification is None:
        return False
    try:
        await deliver_with_timeout(
            adapter,
            dict(notification["payload"]),
            settings.notification_delivery_timeout_seconds,
        )
    except Exception as error:
        await _mark_failed(notification["id"], notification["attempts"], error)
    else:
        await _mark_sent(notification["id"])
    return True


async def run_worker() -> None:
    configure_logging(settings.log_level, service="notification-worker")
    adapter = DemoNotificationAdapter(
        settings.demo_notification_mode,
        settings.notification_delivery_timeout_seconds * 2,
    )
    logger.info("notification_worker_started", extra={"adapter_mode": adapter.mode})
    loop = asyncio.get_running_loop()
    next_reminder_scan = 0.0
    try:
        while True:
            if loop.time() >= next_reminder_scan:
                await enqueue_due_appointment_reminders()
                next_reminder_scan = loop.time() + 5
            processed = await process_one(adapter)
            if not processed:
                await asyncio.sleep(settings.notification_poll_seconds)
    finally:
        await close_engine()


if __name__ == "__main__":
    asyncio.run(run_worker())
