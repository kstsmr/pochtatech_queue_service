from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import BranchResponse, HealthResponse, ServiceResponse
from app.core.config import settings
from app.core.errors import ApiError
from app.db.session import get_connection

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
async def list_branches(connection: AsyncConnection = Depends(get_connection)) -> list[BranchResponse]:
    result = await connection.execute(
        text("SELECT id, postal_code, name, address, timezone FROM branches WHERE active ORDER BY postal_code")
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
