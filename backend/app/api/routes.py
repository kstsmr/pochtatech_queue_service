from datetime import date
from urllib.parse import urlencode
from uuid import UUID, uuid4

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import (
    AppointmentSlotResponse,
    BookingCreateRequest,
    BranchQrResponse,
    BranchResponse,
    HealthResponse,
    QrJoinRequest,
    ServiceResponse,
    TicketResponse,
)
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit_ticket_write
from app.db.session import get_connection
from app.services.prebookings import create_prebooking
from app.services.tickets import (
    activate_if_due,
    add_ticket_event,
    create_client_session,
    idempotency_body,
    idempotent_replay,
    request_fingerprint,
    restore_replay_token,
    save_idempotent_response,
    session_token,
    ticket_response,
    token_hash,
)
from app.services.qr_codes import branch_join_url, branch_qr_svg, public_client_origin

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    database = "down"
    redis_status = "down"
    try:
        from app.db.session import engine

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        database = "up"
    except Exception:
        pass

    client = redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        await client.ping()
        redis_status = "up"
    except Exception:
        pass
    finally:
        await client.aclose()

    if database != "up" or redis_status != "up":
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable", "Service dependencies are unavailable")
    return HealthResponse(status="ok", checks={"database": database, "redis": redis_status})


@router.get("/branches", response_model=list[BranchResponse], tags=["Branches"])
async def list_branches(
    query: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    connection: AsyncConnection = Depends(get_connection),
) -> list[BranchResponse]:
    search = query.strip() if query else None
    result = await connection.execute(
        text(
            """
            SELECT id, postal_code, name, address, timezone
            FROM branches
            WHERE active
              AND (CAST(:search AS text) IS NULL OR postal_code LIKE :prefix
                   OR name ILIKE :pattern OR address ILIKE :pattern)
            ORDER BY postal_code
            LIMIT :limit OFFSET :offset
            """
        ),
        {
            "search": search,
            "prefix": f"{search}%" if search else None,
            "pattern": f"%{search}%" if search else None,
            "limit": limit,
            "offset": offset,
        },
    )
    return [BranchResponse.model_validate(row._mapping) for row in result]


@router.get("/branches/{branch_id}/services", response_model=list[ServiceResponse], tags=["Services"])
async def list_branch_services(
    branch_id: UUID, connection: AsyncConnection = Depends(get_connection)
) -> list[ServiceResponse]:
    branch_exists = await connection.scalar(
        text("SELECT EXISTS(SELECT 1 FROM branches WHERE id = :id AND active)"), {"id": branch_id}
    )
    if not branch_exists:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
    result = await connection.execute(
        text(
            """
            SELECT s.id, s.name, bs.average_service_seconds
            FROM branch_services bs
            JOIN services s ON s.id = bs.service_id
            WHERE bs.branch_id = :branch_id AND bs.active AND s.active
            ORDER BY s.name
            """
        ),
        {"branch_id": branch_id},
    )
    return [ServiceResponse.model_validate(row._mapping) for row in result]


@router.get("/branches/code/{postal_code}", response_model=BranchResponse, tags=["Branches"])
async def get_branch_by_code(
    postal_code: str, connection: AsyncConnection = Depends(get_connection)
) -> BranchResponse:
    if len(postal_code) != 6 or not postal_code.isdigit():
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_branch_code", "Branch code must contain 6 digits")
    result = await connection.execute(
        text("SELECT id, postal_code, name, address, timezone FROM branches WHERE postal_code = :code AND active"),
        {"code": postal_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
    return BranchResponse.model_validate(row)


@router.get(
    "/branches/{branch_id}/queue-qr",
    response_model=BranchQrResponse,
    tags=["Branches"],
)
async def get_branch_queue_qr_info(
    branch_id: UUID,
    public_origin: str | None = Query(default=None, max_length=240),
    connection: AsyncConnection = Depends(get_connection),
) -> BranchQrResponse:
    postal_code = await connection.scalar(
        text("SELECT postal_code FROM branches WHERE id = :branch_id AND active"),
        {"branch_id": branch_id},
    )
    if postal_code is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
    try:
        origin = public_client_origin(public_origin)
    except ValueError as error:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_public_origin", str(error)) from error
    svg_query = f"?{urlencode({'public_origin': origin})}" if public_origin else ""
    return BranchQrResponse(
        branch_id=branch_id,
        postal_code=postal_code,
        join_url=branch_join_url(postal_code, origin),
        qr_svg_path=f"/api/branches/{branch_id}/queue-qr.svg{svg_query}",
    )


@router.get(
    "/branches/{branch_id}/queue-qr.svg",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
    tags=["Branches"],
)
async def get_branch_queue_qr(
    branch_id: UUID,
    public_origin: str | None = Query(default=None, max_length=240),
    connection: AsyncConnection = Depends(get_connection),
) -> Response:
    postal_code = await connection.scalar(
        text("SELECT postal_code FROM branches WHERE id = :branch_id AND active"),
        {"branch_id": branch_id},
    )
    if postal_code is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
    try:
        svg = branch_qr_svg(postal_code, public_origin)
    except ValueError as error:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_public_origin", str(error)) from error
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="queue-{branch_id}.svg"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/branches/{branch_id}/slots",
    response_model=list[AppointmentSlotResponse],
    tags=["Appointments"],
)
async def list_appointment_slots(
    branch_id: UUID,
    service_id: UUID = Query(),
    visit_date: date = Query(alias="date"),
    connection: AsyncConnection = Depends(get_connection),
) -> list[AppointmentSlotResponse]:
    service_exists = await connection.scalar(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM branch_services bs
                JOIN branches b ON b.id = bs.branch_id
                JOIN services s ON s.id = bs.service_id
                WHERE bs.branch_id = :branch_id AND bs.service_id = :service_id
                  AND bs.active AND b.active AND s.active
            )
            """
        ),
        {"branch_id": branch_id, "service_id": service_id},
    )
    if not service_exists:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_service_not_found", "Service is unavailable in this branch")
    result = await connection.execute(
        text(
            """
            WITH inventory AS (
                SELECT slot.id, slot.starts_at, slot.ends_at,
                       LEAST(
                           slot.capacity - slot.reserved,
                           (SELECT count(DISTINCT ws.window_id)
                            FROM window_services ws
                            WHERE ws.branch_id = slot.branch_id
                              AND ws.service_id = slot.service_id)
                           - COALESCE((
                               SELECT sum(same_service.reserved)
                               FROM appointment_slots same_service
                               WHERE same_service.branch_id = slot.branch_id
                                 AND same_service.service_id = slot.service_id
                                 AND same_service.starts_at = slot.starts_at
                                 AND same_service.active
                           ), 0),
                           (SELECT count(*) FROM windows w WHERE w.branch_id = slot.branch_id)
                           - COALESCE((
                               SELECT sum(other.reserved) FROM appointment_slots other
                               WHERE other.branch_id = slot.branch_id
                                 AND other.starts_at = slot.starts_at AND other.active
                           ), 0)
                       )::int AS available
                FROM appointment_slots slot
                JOIN branches b ON b.id = slot.branch_id
                WHERE slot.branch_id = :branch_id AND slot.service_id = :service_id
                  AND (slot.starts_at AT TIME ZONE b.timezone)::date = :visit_date
                  AND slot.active AND slot.starts_at > clock_timestamp()
            )
            SELECT id, starts_at, ends_at, available
            FROM inventory WHERE available > 0
            ORDER BY starts_at
            """
        ),
        {"branch_id": branch_id, "service_id": service_id, "visit_date": visit_date},
    )
    return [AppointmentSlotResponse.model_validate(row) for row in result.mappings()]


@router.post(
    "/bookings",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Appointments"],
)
async def create_booking(
    payload: BookingCreateRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: None = Depends(limit_ticket_write),
    connection: AsyncConnection = Depends(get_connection),
) -> TicketResponse:
    return await create_prebooking(connection, payload, idempotency_key)


@router.post(
    "/queue/join",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Queue"],
)
async def join_queue_by_code(
    payload: QrJoinRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: None = Depends(limit_ticket_write),
    connection: AsyncConnection = Depends(get_connection),
) -> TicketResponse:
    fingerprint = request_fingerprint(payload.model_dump(mode="json"))
    async with connection.begin():
        branch_id = await connection.scalar(
            text("SELECT id FROM branches WHERE postal_code = :code AND active"),
            {"code": payload.branch_code},
        )
        if branch_id is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
        raw_token = session_token(branch_id, idempotency_key, "join_queue")
        replay = await idempotent_replay(
            connection,
            branch_id=branch_id,
            command="join_queue",
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return restore_replay_token(replay, raw_token)
        service_exists = await connection.scalar(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM branch_services bs
                    JOIN services s ON s.id = bs.service_id
                    WHERE bs.branch_id = :branch_id AND bs.service_id = :service_id
                      AND bs.active AND s.active
                )
                """
            ),
            {"branch_id": branch_id, "service_id": payload.service_id},
        )
        if not service_exists:
            raise ApiError(status.HTTP_404_NOT_FOUND, "branch_service_not_found", "Service is unavailable in this branch")

        session_id, raw_token = await create_client_session(connection, branch_id, idempotency_key, "join_queue")
        ticket_id = uuid4()
        await connection.execute(
            text(
                """
                INSERT INTO tickets
                    (id, branch_id, service_id, source, status, session_id, eligible_at)
                VALUES (:id, :branch_id, :service_id, 'qr', 'waiting', :session_id, clock_timestamp())
                """
            ),
            {"id": ticket_id, "branch_id": branch_id, "service_id": payload.service_id, "session_id": session_id},
        )
        await add_ticket_event(
            connection,
            branch_id=branch_id,
            ticket_id=ticket_id,
            version=1,
            action="created",
            old_status=None,
            new_status="waiting",
            before_state=None,
            after_state={"status": "waiting", "source": "qr"},
        )
        response = await ticket_response(connection, ticket_id, raw_token, include_token=True)
        await save_idempotent_response(
            connection,
            branch_id=branch_id,
            command="join_queue",
            key=idempotency_key,
            fingerprint=fingerprint,
            response_status=status.HTTP_201_CREATED,
            body=idempotency_body(response),
        )
        return response


@router.get("/tickets/{ticket_id}", response_model=TicketResponse, tags=["Tickets"])
async def get_ticket(
    ticket_id: UUID,
    session_token_header: str = Header(alias="X-Session-Token", min_length=20),
    connection: AsyncConnection = Depends(get_connection),
) -> TicketResponse:
    async with connection.begin():
        await ticket_response(connection, ticket_id, session_token_header)
        await activate_if_due(connection, ticket_id)
        return await ticket_response(connection, ticket_id, session_token_header)


@router.post("/tickets/{ticket_id}/cancel", response_model=TicketResponse, tags=["Tickets"])
async def cancel_ticket(
    ticket_id: UUID,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    session_token_header: str = Header(alias="X-Session-Token", min_length=20),
    connection: AsyncConnection = Depends(get_connection),
) -> TicketResponse:
    async with connection.begin():
        current = await ticket_response(connection, ticket_id, session_token_header)
        fingerprint = request_fingerprint({"ticket_id": str(ticket_id), "action": "cancel"})
        replay = await idempotent_replay(
            connection,
            branch_id=current.branch_id,
            command="cancel_ticket",
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return TicketResponse.model_validate(replay)

        result = await connection.execute(
            text(
                """
                SELECT t.status, t.slot_id, t.version
                FROM tickets t
                JOIN client_sessions cs ON cs.id = t.session_id
                WHERE t.id = :ticket_id AND cs.token_hash = :token_hash
                FOR UPDATE
                """
            ),
            {"ticket_id": ticket_id, "token_hash": token_hash(session_token_header)},
        )
        ticket = result.mappings().one()
        if ticket["status"] not in {"booked", "waiting"}:
            raise ApiError(status.HTTP_409_CONFLICT, "ticket_not_cancellable", "Ticket can no longer be cancelled")
        new_version = ticket["version"] + 1
        await connection.execute(
            text(
                """
                UPDATE tickets
                SET status = 'cancelled', closed_at = clock_timestamp(), updated_at = clock_timestamp(),
                    version = :version
                WHERE id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id, "version": new_version},
        )
        if ticket["slot_id"] is not None:
            await connection.execute(
                text("UPDATE appointment_slots SET reserved = GREATEST(reserved - 1, 0) WHERE id = :slot_id"),
                {"slot_id": ticket["slot_id"]},
            )
        await add_ticket_event(
            connection,
            branch_id=current.branch_id,
            ticket_id=ticket_id,
            version=new_version,
            action="cancelled",
            old_status=ticket["status"],
            new_status="cancelled",
            before_state={"status": ticket["status"]},
            after_state={"status": "cancelled"},
        )
        response = await ticket_response(connection, ticket_id, session_token_header)
        await save_idempotent_response(
            connection,
            branch_id=current.branch_id,
            command="cancel_ticket",
            key=idempotency_key,
            fingerprint=fingerprint,
            response_status=status.HTTP_200_OK,
            body=idempotency_body(response),
        )
        return response
