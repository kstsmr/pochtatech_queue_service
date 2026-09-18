import hmac
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, status
from fastapi.security import APIKeyHeader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import (
    BookingCreateRequest,
    DemoMobilePrebookingRequest,
    NotificationDeliveryResponse,
    TicketResponse,
)
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit_integration
from app.db.session import get_connection
from app.services.prebookings import create_prebooking

router = APIRouter(prefix="/api/integrations")
demo_mobile_key_header = APIKeyHeader(name="X-Integration-Key", auto_error=False)


def require_demo_mobile_key(
    integration_key: str | None = Depends(demo_mobile_key_header),
) -> None:
    expected = settings.demo_mobile_app_api_key.get_secret_value()
    if integration_key is None or not hmac.compare_digest(integration_key, expected):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_integration_key",
            "Integration credentials are invalid",
        )


@router.post(
    "/demo-mobile/prebookings",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Integrations"],
    dependencies=[Depends(limit_integration), Depends(require_demo_mobile_key)],
    summary="Synchronize a prebooking from the demo mobile application",
)
async def sync_demo_mobile_prebooking(
    payload: DemoMobilePrebookingRequest,
    connection: AsyncConnection = Depends(get_connection),
) -> TicketResponse:
    idempotency_key = uuid5(
        NAMESPACE_URL,
        f"pochta-demo-mobile:{payload.branch_id}:{payload.external_booking_id}",
    )
    booking = BookingCreateRequest.model_validate(payload.model_dump(exclude={"external_booking_id"}))
    return await create_prebooking(
        connection,
        booking,
        idempotency_key,
        command="sync_demo_mobile_prebooking",
        actor_id="demo_mobile_app",
        actor_role="integration",
    )


@router.get(
    "/demo-notifications/{ticket_id}",
    response_model=list[NotificationDeliveryResponse],
    tags=["Integrations"],
    dependencies=[Depends(limit_integration), Depends(require_demo_mobile_key)],
    summary="Inspect demo notification deliveries for a ticket",
)
async def list_demo_notification_deliveries(
    ticket_id: UUID,
    connection: AsyncConnection = Depends(get_connection),
) -> list[NotificationDeliveryResponse]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT n.id, e.ticket_id, n.channel, n.status, n.attempts,
                       n.next_attempt_at, n.last_error, n.delivered_at
                FROM notification_log n
                JOIN ticket_events e ON e.branch_id = n.branch_id AND e.id = n.event_id
                WHERE e.ticket_id = :ticket_id
                ORDER BY n.next_attempt_at, n.id
                """
            ),
            {"ticket_id": ticket_id},
        )
    ).mappings().all()
    return [NotificationDeliveryResponse.model_validate(row) for row in rows]
