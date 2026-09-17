import hmac
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import (
    BranchResponse,
    IncidentCreateRequest,
    IncidentResponse,
    RedirectTicketRequest,
    StaffIdentityResponse,
    StaffLoginRequest,
    StaffLogoutResponse,
    StaffSessionResponse,
    StaffTicketResponse,
    StaffWindowResponse,
    WalkInCreateRequest,
    WindowOpenRequest,
)
from app.core.errors import ApiError
from app.db.session import get_connection
from app.services.staff import (
    StaffIdentity,
    authenticate_staff,
    call_next_ticket,
    close_window,
    complete_ticket,
    create_staff_session,
    create_walk_in,
    list_queue,
    list_windows,
    open_window,
    mark_no_show,
    recall_ticket,
    redirect_ticket,
    return_ticket,
    start_ticket,
    staff_pin_hash,
    staff_token_hash,
)

router = APIRouter(prefix="/api/staff", tags=["Staff"])


async def current_staff(
    authorization: Annotated[str | None, Header()] = None,
    connection: AsyncConnection = Depends(get_connection),
) -> StaffIdentity:
    identity = await authenticate_staff(connection, authorization)
    await connection.rollback()
    return identity


async def current_operator(
    identity: StaffIdentity = Depends(current_staff),
) -> StaffIdentity:
    if identity.role != "operator":
        raise ApiError(status.HTTP_403_FORBIDDEN, "operator_role_required", "Operator access is required")
    return identity


async def window_response(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID
) -> StaffWindowResponse:
    windows = await list_windows(connection, identity)
    for window in windows:
        if window.id == window_id:
            return window
    raise ApiError(status.HTTP_404_NOT_FOUND, "window_not_found", "Window was not found")


@router.post("/login", response_model=StaffSessionResponse)
async def staff_login(
    payload: StaffLoginRequest,
    connection: AsyncConnection = Depends(get_connection),
) -> StaffSessionResponse:
    login_error: ApiError | None = None
    async with connection.begin():
        member = (
            await connection.execute(
                text(
                    """
                    SELECT id, employee_code, display_name, role, pin_salt, pin_hash,
                           active, locked_until
                    FROM staff_members
                    WHERE branch_id = :branch_id AND lower(employee_code) = lower(:employee_code)
                    FOR UPDATE
                    """
                ),
                {"branch_id": payload.branch_id, "employee_code": payload.employee_code.strip()},
            )
        ).mappings().one_or_none()
        candidate_hash = staff_pin_hash(payload.pin, member["pin_salt"] if member else b"\0" * 16)
        credentials_valid = bool(
            member
            and member["active"]
            and hmac.compare_digest(candidate_hash, member["pin_hash"])
        )
        locked = bool(
            member
            and member["locked_until"] is not None
            and await connection.scalar(text("SELECT :locked_until > clock_timestamp()"), {"locked_until": member["locked_until"]})
        )
        if not credentials_valid or locked:
            if member and member["active"] and not locked:
                await connection.execute(
                    text(
                        """
                        UPDATE staff_members
                        SET failed_login_count = failed_login_count + 1,
                            locked_until = CASE WHEN failed_login_count + 1 >= 5
                                THEN clock_timestamp() + interval '15 minutes' ELSE locked_until END,
                            updated_at = clock_timestamp()
                        WHERE id = :id
                        """
                    ),
                    {"id": member["id"]},
                )
            login_error = ApiError(
                status.HTTP_401_UNAUTHORIZED,
                "invalid_staff_credentials",
                "Employee code or PIN is invalid",
            )
        else:
            await connection.execute(
                text(
                    """
                    UPDATE staff_members SET failed_login_count = 0, locked_until = NULL,
                        updated_at = clock_timestamp() WHERE id = :id
                    """
                ),
                {"id": member["id"]},
            )
            token, _, session_data = await create_staff_session(
                connection,
                branch_id=payload.branch_id,
                staff_member_id=member["id"],
                employee_code=member["employee_code"],
                role=member["role"],
            )
            expires_at, branch = session_data
    if login_error:
        raise login_error
    return StaffSessionResponse(
        token=token,
        expires_at=expires_at,
        employee_code=member["employee_code"],
        display_name=member["display_name"],
        role=member["role"],
        branch=BranchResponse.model_validate(branch),
    )


@router.get("/me", response_model=StaffIdentityResponse)
async def staff_me(
    identity: StaffIdentity = Depends(current_staff),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffIdentityResponse:
    branch = (
        await connection.execute(
            text("SELECT id, postal_code, name, address, timezone FROM branches WHERE id = :id"),
            {"id": identity.branch_id},
        )
    ).mappings().one()
    return StaffIdentityResponse(
        employee_code=identity.employee_code,
        display_name=identity.display_name,
        role=identity.role,
        branch=BranchResponse.model_validate(branch),
    )


@router.post("/logout", response_model=StaffLogoutResponse)
async def staff_logout(
    authorization: Annotated[str | None, Header()] = None,
    identity: StaffIdentity = Depends(current_staff),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffLogoutResponse:
    del identity
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    async with connection.begin():
        result = await connection.execute(
            text("UPDATE staff_sessions SET revoked_at = clock_timestamp() WHERE token_hash = :token_hash"),
            {"token_hash": staff_token_hash(token)},
        )
    return StaffLogoutResponse(revoked=result.rowcount == 1)


@router.get("/windows", response_model=list[StaffWindowResponse])
async def staff_windows(
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> list[StaffWindowResponse]:
    return await list_windows(connection, identity)


@router.post("/windows/{window_id}/open", response_model=StaffWindowResponse)
async def staff_open_window(
    window_id: UUID,
    payload: WindowOpenRequest,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffWindowResponse:
    async with connection.begin():
        await open_window(connection, identity, window_id, payload.service_ids)
    return await window_response(connection, identity, window_id)


@router.post("/windows/{window_id}/close", response_model=StaffWindowResponse)
async def staff_close_window(
    window_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffWindowResponse:
    async with connection.begin():
        await close_window(connection, identity, window_id)
    return await window_response(connection, identity, window_id)


@router.get("/queue", response_model=list[StaffTicketResponse])
async def staff_queue(
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> list[StaffTicketResponse]:
    return await list_queue(connection, identity)


@router.post("/walk-ins", response_model=StaffTicketResponse, status_code=status.HTTP_201_CREATED)
async def staff_create_walk_in(
    payload: WalkInCreateRequest,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await create_walk_in(connection, identity, payload.service_id, idempotency_key)


@router.post("/windows/{window_id}/call-next", response_model=StaffTicketResponse)
async def staff_call_next(
    window_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await call_next_ticket(connection, identity, window_id)


@router.post("/tickets/{ticket_id}/start", response_model=StaffTicketResponse)
async def staff_start_ticket(
    ticket_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await start_ticket(connection, identity, ticket_id)


@router.post("/tickets/{ticket_id}/recall", response_model=StaffTicketResponse)
async def staff_recall_ticket(
    ticket_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await recall_ticket(connection, identity, ticket_id)


@router.post("/tickets/{ticket_id}/no-show", response_model=StaffTicketResponse)
async def staff_mark_no_show(
    ticket_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await mark_no_show(connection, identity, ticket_id)


@router.post("/tickets/{ticket_id}/complete", response_model=StaffTicketResponse)
async def staff_complete_ticket(
    ticket_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await complete_ticket(connection, identity, ticket_id)


@router.post("/tickets/{ticket_id}/return", response_model=StaffTicketResponse)
async def staff_return_ticket(
    ticket_id: UUID,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await return_ticket(connection, identity, ticket_id)


@router.post("/tickets/{ticket_id}/redirect", response_model=StaffTicketResponse)
async def staff_redirect_ticket(
    ticket_id: UUID,
    payload: RedirectTicketRequest,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffTicketResponse:
    async with connection.begin():
        return await redirect_ticket(
            connection, identity, ticket_id, payload.service_id, payload.target_window_id
        )


@router.post("/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def staff_create_incident(
    payload: IncidentCreateRequest,
    identity: StaffIdentity = Depends(current_operator),
    connection: AsyncConnection = Depends(get_connection),
) -> IncidentResponse:
    incident_id = uuid4()
    async with connection.begin():
        if payload.window_id is not None:
            window_exists = await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM windows WHERE id = :id AND branch_id = :branch_id)"),
                {"id": payload.window_id, "branch_id": identity.branch_id},
            )
            if not window_exists:
                raise ApiError(status.HTTP_404_NOT_FOUND, "window_not_found", "Window was not found")
        if payload.ticket_id is not None:
            ticket_exists = await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM tickets WHERE id = :id AND branch_id = :branch_id)"),
                {"id": payload.ticket_id, "branch_id": identity.branch_id},
            )
            if not ticket_exists:
                raise ApiError(status.HTTP_404_NOT_FOUND, "ticket_not_found", "Ticket was not found")
        created_at = await connection.scalar(
            text(
                """
                INSERT INTO incidents (id, branch_id, window_id, ticket_id, actor_id, category, description)
                VALUES (:id, :branch_id, :window_id, :ticket_id, :actor_id, :category, :description)
                RETURNING created_at
                """
            ),
            {
                "id": incident_id,
                "branch_id": identity.branch_id,
                "window_id": payload.window_id,
                "ticket_id": payload.ticket_id,
                "actor_id": identity.employee_code,
                "category": payload.category,
                "description": payload.description.strip(),
            },
        )
    return IncidentResponse(
        id=incident_id,
        category=payload.category,
        description=payload.description.strip(),
        created_at=created_at,
    )
