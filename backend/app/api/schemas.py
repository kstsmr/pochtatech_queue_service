from uuid import UUID

from pydantic import BaseModel


class HealthChecks(BaseModel):
    database: str
    redis: str


class HealthResponse(BaseModel):
    status: str
    checks: HealthChecks


class BranchResponse(BaseModel):
    id: UUID
    postal_code: str
    name: str
    address: str
    timezone: str


class ServiceResponse(BaseModel):
    id: UUID
    name: str
    average_service_seconds: int
