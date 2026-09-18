from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import BookingCreateRequest, TicketResponse
from app.core.errors import ApiError
from app.core.priority import early_minutes
from app.services.tickets import (
    add_ticket_event,
    create_client_session,
    idempotency_body,
    idempotent_replay,
    request_fingerprint,
    restore_replay_token,
    save_idempotent_response,
    session_token,
    ticket_response,
)


async def create_prebooking(
    connection: AsyncConnection,
    payload: BookingCreateRequest,
    idempotency_key: UUID,
    *,
    command: str = "create_booking",
    actor_id: str = "client",
    actor_role: str = "client",
) -> TicketResponse:
    """Create one prebooking through the shared transactional domain path."""
    fingerprint = request_fingerprint(payload.model_dump(mode="json"))
    raw_token = session_token(payload.branch_id, idempotency_key, command)
    async with connection.begin():
        replay = await idempotent_replay(
            connection,
            branch_id=payload.branch_id,
            command=command,
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return restore_replay_token(replay, raw_token)

        initial_slot = (
            await connection.execute(
                text(
                    """
                    SELECT id, starts_at
                    FROM appointment_slots
                    WHERE id = :slot_id AND branch_id = :branch_id AND service_id = :service_id
                      AND active AND starts_at > clock_timestamp()
                    """
                ),
                payload.model_dump(),
            )
        ).mappings().one_or_none()
        if initial_slot is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "slot_not_found", "Appointment slot was not found")

        capacity_lock = f"{payload.branch_id}:appointment:{initial_slot['starts_at'].isoformat()}"
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": capacity_lock},
        )
        slot = (
            await connection.execute(
                text(
                    """
                    SELECT id, starts_at, capacity, reserved
                    FROM appointment_slots
                    WHERE id = :slot_id AND branch_id = :branch_id AND service_id = :service_id
                      AND active AND starts_at > clock_timestamp()
                    FOR UPDATE
                    """
                ),
                payload.model_dump(),
            )
        ).mappings().one_or_none()
        if slot is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "slot_not_found", "Appointment slot was not found")

        branch_capacity = int(
            await connection.scalar(
                text("SELECT count(*) FROM windows WHERE branch_id = :branch_id"),
                {"branch_id": payload.branch_id},
            )
            or 0
        )
        service_capacity = int(
            await connection.scalar(
                text(
                    """
                    SELECT count(DISTINCT window_id) FROM window_services
                    WHERE branch_id = :branch_id AND service_id = :service_id
                    """
                ),
                {"branch_id": payload.branch_id, "service_id": payload.service_id},
            )
            or 0
        )
        reserved_at_time = int(
            await connection.scalar(
                text(
                    """
                    SELECT COALESCE(sum(reserved), 0) FROM appointment_slots
                    WHERE branch_id = :branch_id AND starts_at = :starts_at AND active
                    """
                ),
                {"branch_id": payload.branch_id, "starts_at": slot["starts_at"]},
            )
            or 0
        )
        reserved_for_service = int(
            await connection.scalar(
                text(
                    """
                    SELECT COALESCE(sum(reserved), 0) FROM appointment_slots
                    WHERE branch_id = :branch_id AND service_id = :service_id
                      AND starts_at = :starts_at AND active
                    """
                ),
                {
                    "branch_id": payload.branch_id,
                    "service_id": payload.service_id,
                    "starts_at": slot["starts_at"],
                },
            )
            or 0
        )
        if (
            slot["reserved"] >= slot["capacity"]
            or reserved_at_time >= branch_capacity
            or reserved_for_service >= service_capacity
        ):
            raise ApiError(status.HTTP_409_CONFLICT, "slot_full", "Appointment slot is already full")

        session_id, raw_token = await create_client_session(
            connection,
            payload.branch_id,
            idempotency_key,
            command,
            expires_at=slot["starts_at"] + timedelta(days=1),
        )
        ticket_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO tickets
                    (id, branch_id, service_id, source, status, slot_id, session_id,
                     scheduled_time, eligible_at)
                VALUES
                    (:id, :branch_id, :service_id, 'prebooking', 'booked', :slot_id, :session_id,
                     :starts_at, :eligible_at)
                """
            ),
            {
                "id": ticket_id,
                "branch_id": payload.branch_id,
                "service_id": payload.service_id,
                "slot_id": payload.slot_id,
                "session_id": session_id,
                "starts_at": slot["starts_at"],
                "eligible_at": slot["starts_at"] - timedelta(minutes=early_minutes()),
            },
        )
        await connection.execute(
            text("UPDATE appointment_slots SET reserved = reserved + 1 WHERE id = :slot_id"),
            {"slot_id": payload.slot_id},
        )
        await add_ticket_event(
            connection,
            branch_id=payload.branch_id,
            ticket_id=ticket_id,
            version=1,
            action="created",
            old_status=None,
            new_status="booked",
            before_state=None,
            after_state={"status": "booked", "source": "prebooking", "origin": actor_id},
            actor_id=actor_id,
            actor_role=actor_role,
        )
        response = await ticket_response(connection, ticket_id, raw_token, include_token=True)
        await save_idempotent_response(
            connection,
            branch_id=payload.branch_id,
            command=command,
            key=idempotency_key,
            fingerprint=fingerprint,
            response_status=status.HTTP_201_CREATED,
            body=idempotency_body(response),
        )
        return response
