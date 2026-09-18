import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import StaffTicketResponse, StaffWindowResponse
from app.core.errors import ApiError
from app.core.priority import bind_priority_sql, priority_parameters, validate_priority_config
from app.services.tickets import add_ticket_event


@dataclass(frozen=True)
class StaffIdentity:
    session_id: UUID
    branch_id: UUID
    employee_code: str
    display_name: str
    role: str


PIN_ITERATIONS = 210_000


def staff_pin_hash(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS)


def staff_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def authenticate_staff(connection: AsyncConnection, authorization: str | None) -> StaffIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "staff_auth_required", "Employee session is required")
    token = authorization.removeprefix("Bearer ").strip()
    if len(token) < 32:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "staff_auth_invalid", "Employee session is invalid")
    result = await connection.execute(
        text(
            """
            SELECT ss.id AS session_id, ss.branch_id, ss.employee_code,
                   COALESCE(sm.display_name, ss.employee_code) AS display_name, ss.role
            FROM staff_sessions ss
            JOIN staff_members sm ON sm.id = ss.staff_member_id AND sm.branch_id = ss.branch_id
            WHERE ss.token_hash = :token_hash AND ss.expires_at > clock_timestamp()
              AND ss.revoked_at IS NULL AND sm.active
            """
        ),
        {"token_hash": staff_token_hash(token)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "staff_auth_invalid", "Employee session is invalid or expired")
    return StaffIdentity(**row)


async def create_staff_session(
    connection: AsyncConnection, *, branch_id: UUID, staff_member_id: UUID,
    employee_code: str, role: str
) -> tuple[str, UUID, Any]:
    branch = (
        await connection.execute(
            text("SELECT id, postal_code, name, address, timezone FROM branches WHERE id = :id AND active"),
            {"id": branch_id},
        )
    ).mappings().one_or_none()
    if branch is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_not_found", "Branch was not found")
    raw_token = secrets.token_urlsafe(32)
    session_id = uuid4()
    expires_at = await connection.scalar(
        text(
            """
            INSERT INTO staff_sessions
                (id, branch_id, staff_member_id, employee_code, role, token_hash, expires_at)
            VALUES (:id, :branch_id, :staff_member_id, :employee_code, :role, :token_hash,
                    clock_timestamp() + interval '12 hours')
            RETURNING expires_at
            """
        ),
        {
            "id": session_id,
            "branch_id": branch_id,
            "staff_member_id": staff_member_id,
            "employee_code": employee_code.strip(),
            "role": role,
            "token_hash": staff_token_hash(raw_token),
        },
    )
    return raw_token, session_id, (expires_at, branch)


async def recall_ticket(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    if ticket["status"] != "called":
        raise ApiError(status.HTTP_409_CONFLICT, "ticket_not_called", "Only a called ticket can be recalled")
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET called_at = clock_timestamp(), updated_at = clock_timestamp(),
                version = :version WHERE id = :ticket_id
            """
        ),
        {"version": version, "ticket_id": ticket_id},
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="recalled", old_status="called", new_status="called",
        before_state={"status": "called"}, after_state={"status": "called"},
        actor_id=identity.employee_code, actor_role=identity.role,
    )
    return await staff_ticket_response(connection, ticket_id)


async def mark_no_show(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    if ticket["status"] != "called":
        raise ApiError(status.HTTP_409_CONFLICT, "ticket_not_called", "Only a called ticket can be marked as no-show")
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'no_show', window_id = NULL, target_window_id = NULL,
                closed_at = clock_timestamp(), updated_at = clock_timestamp(), version = :version
            WHERE id = :ticket_id
            """
        ),
        {"version": version, "ticket_id": ticket_id},
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="no_show", old_status="called", new_status="no_show",
        before_state={"status": "called", "window_id": str(ticket["window_id"])},
        after_state={"status": "no_show"}, actor_id=identity.employee_code, actor_role=identity.role,
    )
    await _finish_draining_window(connection, identity, ticket["window_id"])
    return await staff_ticket_response(connection, ticket_id)


async def add_window_event(
    connection: AsyncConnection,
    *,
    branch_id: UUID,
    window_id: UUID,
    version: int,
    actor_id: str,
    action: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO window_events
                (id, branch_id, window_id, window_version, actor_id, action, before_state, after_state)
            VALUES
                (:id, :branch_id, :window_id, :version, :actor_id, :action,
                 CAST(:before_state AS jsonb), CAST(:after_state AS jsonb))
            """
        ),
        {
            "id": uuid4(),
            "branch_id": branch_id,
            "window_id": window_id,
            "version": version,
            "actor_id": actor_id,
            "action": action,
            "before_state": json.dumps(before_state) if before_state is not None else None,
            "after_state": json.dumps(after_state),
        },
    )


async def release_targeted_tickets(
    connection: AsyncConnection, *, identity: StaffIdentity, window_id: UUID
) -> None:
    released = (
        await connection.execute(
            text(
                """
                UPDATE tickets
                SET target_window_id = NULL, updated_at = clock_timestamp(), version = version + 1
                WHERE branch_id = :branch_id AND target_window_id = :window_id AND status = 'waiting'
                RETURNING id, version
                """
            ),
            {"branch_id": identity.branch_id, "window_id": window_id},
        )
    ).mappings().all()
    for ticket in released:
        await add_ticket_event(
            connection,
            branch_id=identity.branch_id,
            ticket_id=ticket["id"],
            version=ticket["version"],
            action="target_window_released",
            old_status="waiting",
            new_status="waiting",
            before_state={"status": "waiting", "target_window_id": str(window_id)},
            after_state={"status": "waiting", "target_window_id": None},
            actor_id=identity.employee_code,
            actor_role=identity.role,
            reason="Target window closed",
        )


async def staff_ticket_response(connection: AsyncConnection, ticket_id: UUID) -> StaffTicketResponse:
    row = (
        await connection.execute(
            text(
                """
                SELECT t.id, t.ticket_number, t.source, t.status, t.service_id, s.name AS service_name,
                       t.window_id, w.number AS window_number, t.target_window_id, t.scheduled_time,
                       t.created_at, t.called_at, t.return_count, t.redirect_count,
                       GREATEST(0, floor(extract(epoch FROM
                           (clock_timestamp() - COALESCE(t.eligible_at, t.created_at))) / 60))::int AS waiting_minutes
                FROM tickets t
                JOIN services s ON s.id = t.service_id
                LEFT JOIN windows w ON w.id = t.window_id
                WHERE t.id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "ticket_not_found", "Ticket was not found")
    return StaffTicketResponse.model_validate(row)


async def list_queue(connection: AsyncConnection, identity: StaffIdentity) -> list[StaffTicketResponse]:
    rule = (
        await connection.execute(
            text(
                """
                SELECT version, config FROM priority_rules
                WHERE branch_id = :branch_id AND active ORDER BY version DESC LIMIT 1
                """
            ),
            {"branch_id": identity.branch_id},
        )
    ).mappings().one_or_none()
    if rule is None:
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, "priority_rule_missing", "Queue priority rule is unavailable")
    try:
        config = validate_priority_config(rule["config"])
        if int(config["rule_version"]) != rule["version"]:
            raise ValueError("priority rule version does not match its payload")
    except ValueError as error:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "priority_rule_invalid",
            "Active queue priority rule is invalid",
        ) from error
    rows = (
        await connection.execute(
            text(
                bind_priority_sql(
                    """
                SELECT t.id
                FROM tickets t
                WHERE t.branch_id = :branch_id
                  AND (
                    t.status IN ('waiting', 'called', 'serving')
                    OR (t.status = 'booked' AND t.eligible_at <= clock_timestamp())
                  )
                ORDER BY
                    CASE t.status WHEN 'serving' THEN 0 WHEN 'called' THEN 1 WHEN 'waiting' THEN 2 ELSE 3 END,
                    CASE WHEN t.status = 'waiting' THEN /* PRIORITY_EXPRESSION */ ELSE 0 END,
                    t.eligible_at, t.queue_sequence, t.id
                LIMIT 200
                """,
                    "t",
                )
            ),
            {"branch_id": identity.branch_id, **priority_parameters(config)},
        )
    ).scalars().all()
    return [await staff_ticket_response(connection, ticket_id) for ticket_id in rows]


async def list_unfinished_tickets(
    connection: AsyncConnection, identity: StaffIdentity
) -> list[StaffTicketResponse]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT id FROM tickets
                WHERE branch_id = :branch_id
                  AND status IN ('booked', 'waiting', 'called', 'serving')
                ORDER BY
                  CASE status WHEN 'serving' THEN 0 WHEN 'called' THEN 1
                              WHEN 'waiting' THEN 2 ELSE 3 END,
                  eligible_at, queue_sequence, id
                LIMIT 200
                """
            ),
            {"branch_id": identity.branch_id},
        )
    ).scalars().all()
    return [await staff_ticket_response(connection, ticket_id) for ticket_id in rows]


async def list_windows(connection: AsyncConnection, identity: StaffIdentity) -> list[StaffWindowResponse]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT w.id, w.number, w.status, w.version, w.operator_session_id,
                       ss.employee_code AS operator_code,
                       COALESCE(array_agg(ws.service_id ORDER BY ws.service_id)
                           FILTER (WHERE ws.service_id IS NOT NULL), ARRAY[]::uuid[]) AS service_ids,
                       COALESCE(array_agg(s.name ORDER BY ws.service_id)
                           FILTER (WHERE s.name IS NOT NULL), ARRAY[]::text[]) AS service_names
                FROM windows w
                LEFT JOIN staff_sessions ss ON ss.id = w.operator_session_id
                LEFT JOIN window_services ws ON ws.branch_id = w.branch_id AND ws.window_id = w.id
                LEFT JOIN services s ON s.id = ws.service_id
                WHERE w.branch_id = :branch_id
                GROUP BY w.id, ss.employee_code
                ORDER BY w.number
                """
            ),
            {"branch_id": identity.branch_id},
        )
    ).mappings().all()
    windows: list[StaffWindowResponse] = []
    for row in rows:
        active_id = await connection.scalar(
            text(
                """
                SELECT id FROM tickets
                WHERE branch_id = :branch_id AND window_id = :window_id
                  AND status IN ('called', 'serving')
                """
            ),
            {"branch_id": identity.branch_id, "window_id": row["id"]},
        )
        windows.append(
            StaffWindowResponse(
                id=row["id"],
                number=row["number"],
                status=row["status"],
                version=row["version"],
                owned_by_current_session=row["operator_session_id"] == identity.session_id,
                operator_code=row["operator_code"],
                service_ids=list(row["service_ids"]),
                service_names=list(row["service_names"]),
                active_ticket=await staff_ticket_response(connection, active_id) if active_id else None,
            )
        )
    return windows


async def _locked_owned_window(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID
) -> Any:
    row = (
        await connection.execute(
            text("SELECT * FROM windows WHERE id = :id AND branch_id = :branch_id FOR UPDATE"),
            {"id": window_id, "branch_id": identity.branch_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "window_not_found", "Window was not found")
    if row["operator_session_id"] != identity.session_id:
        raise ApiError(status.HTTP_409_CONFLICT, "window_not_owned", "Window belongs to another workstation")
    return row


async def open_window(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID, service_ids: list[UUID]
) -> None:
    if len(set(service_ids)) != len(service_ids):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "duplicate_services", "Services must be unique")
    window = (
        await connection.execute(
            text("SELECT * FROM windows WHERE id = :id AND branch_id = :branch_id FOR UPDATE"),
            {"id": window_id, "branch_id": identity.branch_id},
        )
    ).mappings().one_or_none()
    if window is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "window_not_found", "Window was not found")
    if window["status"] != "closed":
        raise ApiError(status.HTTP_409_CONFLICT, "window_already_open", "Window is already open")
    owns_other = await connection.scalar(
        text("SELECT EXISTS(SELECT 1 FROM windows WHERE operator_session_id = :session_id)"),
        {"session_id": identity.session_id},
    )
    if owns_other:
        raise ApiError(status.HTTP_409_CONFLICT, "operator_already_at_window", "Close the current window first")
    available_count = await connection.scalar(
        text(
            """
            SELECT count(*) FROM branch_services bs JOIN services s ON s.id = bs.service_id
            WHERE bs.branch_id = :branch_id AND bs.active AND s.active
              AND bs.service_id = ANY(CAST(:service_ids AS uuid[]))
            """
        ),
        {"branch_id": identity.branch_id, "service_ids": service_ids},
    )
    if available_count != len(service_ids):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_window_services", "A service is unavailable")
    await connection.execute(
        text("DELETE FROM window_services WHERE branch_id = :branch_id AND window_id = :window_id"),
        {"branch_id": identity.branch_id, "window_id": window_id},
    )
    await connection.execute(
        text(
            """
            INSERT INTO window_services (branch_id, window_id, service_id)
            SELECT :branch_id, :window_id, unnest(CAST(:service_ids AS uuid[]))
            """
        ),
        {"branch_id": identity.branch_id, "window_id": window_id, "service_ids": service_ids},
    )
    version = window["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE windows SET status = 'open', operator_session_id = :session_id, version = :version
            WHERE id = :window_id
            """
        ),
        {"session_id": identity.session_id, "version": version, "window_id": window_id},
    )
    await add_window_event(
        connection,
        branch_id=identity.branch_id,
        window_id=window_id,
        version=version,
        actor_id=identity.employee_code,
        action="opened",
        before_state={"status": "closed"},
        after_state={"status": "open", "service_ids": [str(item) for item in service_ids]},
    )


async def close_window(connection: AsyncConnection, identity: StaffIdentity, window_id: UUID) -> None:
    window = await _locked_owned_window(connection, identity, window_id)
    active = await connection.scalar(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM tickets WHERE branch_id = :branch_id AND window_id = :window_id
                          AND status IN ('called', 'serving'))
            """
        ),
        {"branch_id": identity.branch_id, "window_id": window_id},
    )
    new_status = "draining" if active else "closed"
    version = window["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE windows SET status = :status,
                operator_session_id = CASE WHEN :status = 'closed' THEN NULL ELSE operator_session_id END,
                version = :version
            WHERE id = :window_id
            """
        ),
        {"status": new_status, "version": version, "window_id": window_id},
    )
    await add_window_event(
        connection,
        branch_id=identity.branch_id,
        window_id=window_id,
        version=version,
        actor_id=identity.employee_code,
        action="draining" if active else "closed",
        before_state={"status": window["status"]},
        after_state={"status": new_status},
    )
    await release_targeted_tickets(connection, identity=identity, window_id=window_id)


async def _activate_due_bookings(connection: AsyncConnection, identity: StaffIdentity) -> None:
    activated = (
        await connection.execute(
            text(
                """
                UPDATE tickets SET status = 'waiting', updated_at = clock_timestamp(), version = version + 1
                WHERE branch_id = :branch_id AND status = 'booked' AND eligible_at <= clock_timestamp()
                RETURNING id, version
                """
            ),
            {"branch_id": identity.branch_id},
        )
    ).mappings().all()
    for ticket in activated:
        await add_ticket_event(
            connection,
            branch_id=identity.branch_id,
            ticket_id=ticket["id"],
            version=ticket["version"],
            action="activated",
            old_status="booked",
            new_status="waiting",
            before_state={"status": "booked"},
            after_state={"status": "waiting"},
            actor_id="queue-engine",
            actor_role="system",
        )


async def call_next_ticket(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID
) -> StaffTicketResponse:
    window = await _locked_owned_window(connection, identity, window_id)
    if window["status"] != "open":
        raise ApiError(status.HTTP_409_CONFLICT, "window_not_open", "Window is not accepting new clients")
    active = await connection.scalar(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM tickets WHERE branch_id = :branch_id AND window_id = :window_id
                          AND status IN ('called', 'serving'))
            """
        ),
        {"branch_id": identity.branch_id, "window_id": window_id},
    )
    if active:
        raise ApiError(status.HTTP_409_CONFLICT, "window_busy", "Complete or return the current client first")
    await _activate_due_bookings(connection, identity)
    rule_row = (
        await connection.execute(
            text(
                """
                SELECT version, config FROM priority_rules
                WHERE branch_id = :branch_id AND active ORDER BY version DESC LIMIT 1
                """
            ),
            {"branch_id": identity.branch_id},
        )
    ).mappings().one()
    try:
        config = validate_priority_config(rule_row["config"])
        if int(config["rule_version"]) != rule_row["version"]:
            raise ValueError("priority rule version does not match its payload")
    except ValueError as error:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "priority_rule_invalid",
            "Active queue priority rule is invalid",
        ) from error
    ticket = (
        await connection.execute(
            text(
                bind_priority_sql(
                    """
                SELECT t.id, t.version
                FROM tickets t
                JOIN window_services ws ON ws.branch_id = t.branch_id
                    AND ws.window_id = :window_id AND ws.service_id = t.service_id
                WHERE t.branch_id = :branch_id AND t.status = 'waiting'
                  AND (t.target_window_id IS NULL OR t.target_window_id = :window_id)
                ORDER BY
                  /* PRIORITY_EXPRESSION */,
                  t.eligible_at, t.queue_sequence, t.id
                FOR UPDATE OF t SKIP LOCKED
                LIMIT 1
                """,
                    "t",
                )
            ),
            {
                "window_id": window_id,
                "branch_id": identity.branch_id,
                **priority_parameters(config),
            },
        )
    ).mappings().one_or_none()
    if ticket is None:
        raise ApiError(status.HTTP_409_CONFLICT, "queue_empty", "No compatible clients are waiting")
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'called', window_id = :window_id, target_window_id = NULL,
                called_at = clock_timestamp(), updated_at = clock_timestamp(), version = :version
            WHERE id = :ticket_id
            """
        ),
        {"window_id": window_id, "version": version, "ticket_id": ticket["id"]},
    )
    await add_ticket_event(
        connection,
        branch_id=identity.branch_id,
        ticket_id=ticket["id"],
        version=version,
        action="called",
        old_status="waiting",
        new_status="called",
        before_state={"status": "waiting"},
        after_state={"status": "called", "window_id": str(window_id)},
        actor_id=identity.employee_code,
        actor_role=identity.role,
        rule_version=rule_row["version"],
    )
    return await staff_ticket_response(connection, ticket["id"])


async def create_walk_in(
    connection: AsyncConnection,
    identity: StaffIdentity,
    service_id: UUID,
    idempotency_key: UUID,
) -> StaffTicketResponse:
    lock_name = f"{identity.branch_id}:staff:{identity.session_id}:walk_in:{idempotency_key}"
    await connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": lock_name})
    fingerprint = hashlib.sha256(str(service_id).encode()).hexdigest()
    existing = (
        await connection.execute(
        text(
            """
            SELECT request_hash, (response_body ->> 'id')::uuid AS ticket_id
            FROM idempotency_requests
            WHERE branch_id = :branch_id AND actor_scope = :scope
              AND command = 'create_walk_in' AND key = :key
            """
        ),
        {"branch_id": identity.branch_id, "scope": f"staff:{identity.session_id}", "key": idempotency_key},
        )
    ).mappings().one_or_none()
    if existing:
        if not hmac.compare_digest(existing["request_hash"], fingerprint):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "idempotency_key_reused",
                "Idempotency-Key was already used with another service",
            )
        return await staff_ticket_response(connection, existing["ticket_id"])
    service_exists = await connection.scalar(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM branch_services bs JOIN services s ON s.id = bs.service_id
                          WHERE bs.branch_id = :branch_id AND bs.service_id = :service_id
                            AND bs.active AND s.active)
            """
        ),
        {"branch_id": identity.branch_id, "service_id": service_id},
    )
    if not service_exists:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_service_not_found", "Service is unavailable")
    ticket_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO tickets (id, branch_id, service_id, source, status, eligible_at)
            VALUES (:id, :branch_id, :service_id, 'walk_in', 'waiting', clock_timestamp())
            """
        ),
        {"id": ticket_id, "branch_id": identity.branch_id, "service_id": service_id},
    )
    await add_ticket_event(
        connection,
        branch_id=identity.branch_id,
        ticket_id=ticket_id,
        version=1,
        action="created",
        old_status=None,
        new_status="waiting",
        before_state=None,
        after_state={"status": "waiting", "source": "walk_in"},
        actor_id=identity.employee_code,
        actor_role=identity.role,
    )
    response = await staff_ticket_response(connection, ticket_id)
    await connection.execute(
        text(
            """
            INSERT INTO idempotency_requests
                (branch_id, actor_scope, command, key, request_hash, response_status, response_body)
            VALUES (:branch_id, :scope, 'create_walk_in', :key, :hash, 201, CAST(:body AS jsonb))
            """
        ),
        {
            "branch_id": identity.branch_id,
            "scope": f"staff:{identity.session_id}",
            "key": idempotency_key,
            "hash": fingerprint,
            "body": response.model_dump_json(),
        },
    )
    return response


async def _locked_active_ticket(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> Any:
    row = (
        await connection.execute(
            text(
                """
                SELECT t.* FROM tickets t
                JOIN windows w ON w.id = t.window_id AND w.branch_id = t.branch_id
                WHERE t.id = :ticket_id AND t.branch_id = :branch_id
                  AND w.operator_session_id = :session_id
                  AND t.status IN ('called', 'serving')
                FOR UPDATE OF t
                """
            ),
            {"ticket_id": ticket_id, "branch_id": identity.branch_id, "session_id": identity.session_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_409_CONFLICT, "ticket_not_at_workstation", "Ticket is not active at this workstation")
    return row


async def _finish_draining_window(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID
) -> None:
    window = (
        await connection.execute(
            text(
                """
                UPDATE windows SET status = 'closed', operator_session_id = NULL, version = version + 1
                WHERE id = :window_id AND status = 'draining'
                RETURNING branch_id, version
                """
            ),
            {"window_id": window_id},
        )
    ).mappings().one_or_none()
    if window:
        await add_window_event(
            connection,
            branch_id=window["branch_id"],
            window_id=window_id,
            version=window["version"],
            actor_id=identity.employee_code,
            action="closed_after_active_ticket",
            before_state={"status": "draining"},
            after_state={"status": "closed"},
        )
        await release_targeted_tickets(connection, identity=identity, window_id=window_id)


async def start_ticket(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    if ticket["status"] != "called":
        raise ApiError(status.HTTP_409_CONFLICT, "ticket_not_called", "Only a called ticket can be started")
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'serving', service_started_at = clock_timestamp(),
                updated_at = clock_timestamp(), version = :version WHERE id = :ticket_id
            """
        ),
        {"version": version, "ticket_id": ticket_id},
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="service_started", old_status="called", new_status="serving",
        before_state={"status": "called"}, after_state={"status": "serving"},
        actor_id=identity.employee_code, actor_role=identity.role,
    )
    return await staff_ticket_response(connection, ticket_id)

async def complete_ticket(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    if ticket["status"] != "serving":
        raise ApiError(status.HTTP_409_CONFLICT, "service_not_started", "Start service before completing it")
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'served', window_id = NULL, target_window_id = NULL,
                closed_at = clock_timestamp(), updated_at = clock_timestamp(), version = :version
            WHERE id = :ticket_id
            """
        ),
        {"version": version, "ticket_id": ticket_id},
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="completed", old_status=ticket["status"], new_status="served",
        before_state={"status": ticket["status"], "window_id": str(ticket["window_id"])},
        after_state={"status": "served"}, actor_id=identity.employee_code, actor_role=identity.role,
    )
    await _finish_draining_window(connection, identity, ticket["window_id"])
    return await staff_ticket_response(connection, ticket_id)

async def return_ticket(
    connection: AsyncConnection, identity: StaffIdentity, ticket_id: UUID
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'waiting', window_id = NULL, target_window_id = NULL,
                service_started_at = NULL, updated_at = clock_timestamp(), version = :version,
                return_count = return_count + 1
            WHERE id = :ticket_id
            """
        ),
        {"version": version, "ticket_id": ticket_id},
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="returned", old_status=ticket["status"], new_status="waiting",
        before_state={"status": ticket["status"], "window_id": str(ticket["window_id"])},
        after_state={"status": "waiting"}, actor_id=identity.employee_code, actor_role=identity.role,
    )
    await _finish_draining_window(connection, identity, ticket["window_id"])
    return await staff_ticket_response(connection, ticket_id)


async def redirect_ticket(
    connection: AsyncConnection,
    identity: StaffIdentity,
    ticket_id: UUID,
    service_id: UUID | None,
    target_window_id: UUID | None,
) -> StaffTicketResponse:
    ticket = await _locked_active_ticket(connection, identity, ticket_id)
    new_service_id = service_id or ticket["service_id"]
    if new_service_id == ticket["service_id"] and target_window_id is None:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "redirect_target_required", "Choose another service or window")
    service_exists = await connection.scalar(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM branch_services WHERE branch_id = :branch_id
                          AND service_id = :service_id AND active)
            """
        ),
        {"branch_id": identity.branch_id, "service_id": new_service_id},
    )
    if not service_exists:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_service_not_found", "Service is unavailable")
    if target_window_id is not None:
        target_ok = await connection.scalar(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM windows w JOIN window_services ws
                      ON ws.branch_id = w.branch_id AND ws.window_id = w.id
                    WHERE w.id = :window_id AND w.branch_id = :branch_id AND w.status = 'open'
                      AND ws.service_id = :service_id
                )
                """
            ),
            {"window_id": target_window_id, "branch_id": identity.branch_id, "service_id": new_service_id},
        )
        if not target_ok:
            raise ApiError(status.HTTP_409_CONFLICT, "redirect_window_unavailable", "Target window cannot accept this service")
    if new_service_id != ticket["service_id"] and ticket["slot_id"] is not None:
        await connection.execute(
            text("UPDATE appointment_slots SET reserved = GREATEST(reserved - 1, 0) WHERE id = :slot_id"),
            {"slot_id": ticket["slot_id"]},
        )
    version = ticket["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE tickets SET status = 'waiting', service_id = :service_id,
                window_id = NULL, target_window_id = :target_window_id,
                slot_id = CASE WHEN service_id <> :service_id THEN NULL ELSE slot_id END,
                service_started_at = NULL, updated_at = clock_timestamp(), version = :version,
                redirect_count = redirect_count + 1
            WHERE id = :ticket_id
            """
        ),
        {
            "service_id": new_service_id,
            "target_window_id": target_window_id,
            "version": version,
            "ticket_id": ticket_id,
        },
    )
    await add_ticket_event(
        connection, branch_id=identity.branch_id, ticket_id=ticket_id, version=version,
        action="redirected", old_status=ticket["status"], new_status="waiting",
        before_state={"status": ticket["status"], "service_id": str(ticket["service_id"]),
                      "window_id": str(ticket["window_id"])},
        after_state={"status": "waiting", "service_id": str(new_service_id),
                     "target_window_id": str(target_window_id) if target_window_id else None},
        actor_id=identity.employee_code, actor_role=identity.role,
    )
    await _finish_draining_window(connection, identity, ticket["window_id"])
    return await staff_ticket_response(connection, ticket_id)
