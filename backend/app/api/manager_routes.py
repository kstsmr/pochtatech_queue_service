from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import (
    ManagerActionResponse,
    ManagerDashboardResponse,
    ManagerPriorityResponse,
    ManagerPriorityUpdateRequest,
    ManagerServiceResponse,
    ManagerServiceUpdateRequest,
    ManagerWindowServicesRequest,
    StaffWindowResponse,
)
from app.api.staff_routes import current_staff
from app.core.errors import ApiError
from app.db.session import get_connection
from app.services.manager import (
    manager_close_window,
    manager_dashboard,
    resolve_incident,
    update_priority_rule,
    update_service,
    update_window_services,
)
from app.services.staff import StaffIdentity


router = APIRouter(prefix="/api/manager", tags=["Manager"])


async def current_manager(identity: StaffIdentity = Depends(current_staff)) -> StaffIdentity:
    if identity.role != "manager":
        raise ApiError(status.HTTP_403_FORBIDDEN, "manager_role_required", "Manager access is required")
    return identity


@router.get("/dashboard", response_model=ManagerDashboardResponse)
async def get_manager_dashboard(
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> ManagerDashboardResponse:
    return await manager_dashboard(connection, identity)


@router.put("/services/{service_id}", response_model=ManagerServiceResponse)
async def put_manager_service(
    service_id: UUID,
    payload: ManagerServiceUpdateRequest,
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> ManagerServiceResponse:
    async with connection.begin():
        return await update_service(
            connection,
            identity,
            service_id,
            active=payload.active,
            average_service_seconds=payload.average_service_seconds,
        )


@router.put("/windows/{window_id}/services", response_model=StaffWindowResponse)
async def put_manager_window_services(
    window_id: UUID,
    payload: ManagerWindowServicesRequest,
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffWindowResponse:
    async with connection.begin():
        return await update_window_services(connection, identity, window_id, payload.service_ids)


@router.post("/windows/{window_id}/close", response_model=StaffWindowResponse)
async def post_manager_close_window(
    window_id: UUID,
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> StaffWindowResponse:
    async with connection.begin():
        return await manager_close_window(connection, identity, window_id)


@router.put("/priority", response_model=ManagerPriorityResponse)
async def put_manager_priority(
    payload: ManagerPriorityUpdateRequest,
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> ManagerPriorityResponse:
    async with connection.begin():
        return await update_priority_rule(connection, identity, payload)


@router.post("/incidents/{incident_id}/resolve", response_model=ManagerActionResponse)
async def post_resolve_incident(
    incident_id: UUID,
    identity: StaffIdentity = Depends(current_manager),
    connection: AsyncConnection = Depends(get_connection),
) -> ManagerActionResponse:
    async with connection.begin():
        await resolve_incident(connection, identity, incident_id)
    return ManagerActionResponse(success=True)
