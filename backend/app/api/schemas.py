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


class StaffLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    employee_code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-zА-Яа-яЁё0-9._ -]+$")
    pin: str = Field(min_length=4, max_length=64)


class StaffSessionResponse(BaseModel):
    token: str
    expires_at: datetime
    employee_code: str
    display_name: str
    role: Literal["operator", "manager"]
    branch: BranchResponse


class StaffIdentityResponse(BaseModel):
    employee_code: str
    display_name: str
    role: Literal["operator", "manager"]
    branch: BranchResponse


class StaffTicketResponse(BaseModel):
    id: UUID
    ticket_number: int
    source: Literal["prebooking", "qr", "walk_in"]
    status: Literal["booked", "waiting", "called", "serving", "served", "no_show", "cancelled"]
    service_id: UUID
    service_name: str
    window_id: UUID | None
    window_number: int | None
    target_window_id: UUID | None
    scheduled_time: datetime | None
    created_at: datetime
    called_at: datetime | None
    waiting_minutes: int
    return_count: int
    redirect_count: int


class StaffWindowResponse(BaseModel):
    id: UUID
    number: int
    status: Literal["closed", "open", "draining"]
    version: int
    owned_by_current_session: bool
    operator_code: str | None
    service_ids: list[UUID]
    service_names: list[str]
    active_ticket: StaffTicketResponse | None


class WindowOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_ids: list[UUID] = Field(min_length=1)


class WalkInCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: UUID


class RedirectTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: UUID | None = None
    target_window_id: UUID | None = None


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["technical", "operational"]
    description: str = Field(min_length=5, max_length=1000)
    window_id: UUID | None = None
    ticket_id: UUID | None = None


class IncidentResponse(BaseModel):
    id: UUID
    category: Literal["technical", "operational"]
    description: str
    created_at: datetime


class StaffLogoutResponse(BaseModel):
    revoked: bool
