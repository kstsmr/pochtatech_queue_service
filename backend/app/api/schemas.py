from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class BranchQrResponse(BaseModel):
    branch_id: UUID
    postal_code: str
    join_url: str
    qr_svg_path: str


class ServiceResponse(BaseModel):
    id: UUID
    name: str
    average_service_seconds: int


class AppointmentSlotResponse(BaseModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    available: int = Field(ge=0)


class BookingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    service_id: UUID
    slot_id: UUID


class QrJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_code: str = Field(pattern=r"^\d{6}$")
    service_id: UUID


class TicketResponse(BaseModel):
    id: UUID
    branch_id: UUID
    service_id: UUID
    ticket_number: int
    source: Literal["prebooking", "qr", "walk_in"]
    status: Literal["booked", "waiting", "called", "serving", "served", "no_show", "cancelled"]
    scheduled_time: datetime | None
    created_at: datetime
    updated_at: datetime
    window_number: int | None
    position: int | None
    estimated_wait_minutes: int | None
    branch_name: str
    branch_address: str
    service_name: str
    session_token: str | None = None


class TicketLookupResponse(TicketResponse):
    session_token: None = None
