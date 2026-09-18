import base64
import hashlib
import hmac
import json
import math
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import TicketResponse
from app.core.config import settings
from app.core.errors import ApiError
from app.core.priority import bind_priority_sql, priority_parameters, validate_priority_config
from app.services.notifications import enqueue_ticket_notification


def request_fingerprint(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def session_token(branch_id: UUID, idempotency_key: UUID, command: str) -> str:
    secret = settings.session_token_secret.get_secret_value().encode()
    message = f"{branch_id}:{command}:{idempotency_key}".encode()
    digest = hmac.new(secret, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def idempotent_replay(
    connection: AsyncConnection,
    *,
    branch_id: UUID,
    command: str,
    key: UUID,
    fingerprint: str,
) -> dict[str, Any] | None:
    lock_name = f"{branch_id}:client:{command}:{key}"
    await connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": lock_name})
    result = await connection.execute(
        text(
            """
            SELECT request_hash, response_body
            FROM idempotency_requests
            WHERE branch_id = :branch_id AND actor_scope = 'client'
              AND command = :command AND key = :key
            """
        ),
        {"branch_id": branch_id, "command": command, "key": key},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    if not hmac.compare_digest(row["request_hash"], fingerprint):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "idempotency_key_reused",
            "Idempotency-Key was already used with a different request",
        )
    return dict(row["response_body"])


async def save_idempotent_response(
    connection: AsyncConnection,
    *,
    branch_id: UUID,
    command: str,
    key: UUID,
    fingerprint: str,
    response_status: int,
    body: dict[str, Any],
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO idempotency_requests
                (branch_id, actor_scope, command, key, request_hash, response_status, response_body)
            VALUES (:branch_id, 'client', :command, :key, :request_hash, :response_status, CAST(:body AS jsonb))
            """
        ),
        {
            "branch_id": branch_id,
            "command": command,
            "key": key,
            "request_hash": fingerprint,
            "response_status": response_status,
            "body": json.dumps(body, ensure_ascii=True, separators=(",", ":")),
        },
    )


async def create_client_session(
    connection: AsyncConnection,
    branch_id: UUID,
    idempotency_key: UUID,
    command: str,
    *,
    expires_at: datetime | None = None,
) -> tuple[UUID, str]:
    raw_token = session_token(branch_id, idempotency_key, command)
    session_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO client_sessions (id, token_hash, expires_at)
            VALUES (
                :id,
                :token_hash,
                GREATEST(
                    clock_timestamp() + interval '7 days',
                    COALESCE(CAST(:expires_at AS timestamptz), clock_timestamp())
                )
            )
            """
        ),
        {"id": session_id, "token_hash": token_hash(raw_token), "expires_at": expires_at},
    )
    return session_id, raw_token


async def add_ticket_event(
    connection: AsyncConnection,
    *,
    branch_id: UUID,
    ticket_id: UUID,
    version: int,
    action: str,
    old_status: str | None,
    new_status: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    actor_id: str = "client",
    actor_role: str = "client",
    reason: str | None = None,
    rule_version: int | None = None,
) -> UUID:
    event_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO ticket_events
                (id, branch_id, ticket_id, ticket_version, action, actor_id, actor_role,
                 old_status, new_status, before_state, after_state, reason, rule_version)
            VALUES
                (:id, :branch_id, :ticket_id, :version, :action, :actor_id, :actor_role,
                 :old_status, :new_status, CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                 :reason, :rule_version)
            """
        ),
        {
            "id": event_id,
            "branch_id": branch_id,
            "ticket_id": ticket_id,
            "version": version,
            "action": action,
            "old_status": old_status,
            "new_status": new_status,
            "before_state": json.dumps(before_state) if before_state is not None else None,
            "after_state": json.dumps(after_state),
            "actor_id": actor_id,
            "actor_role": actor_role,
            "reason": reason,
            "rule_version": rule_version,
        },
    )
    if action in {"created", "called", "recalled"}:
        kind = "ticket_created" if action == "created" else "window_called"
        channel = "demo_status" if action == "created" else "demo_call"
        await enqueue_ticket_notification(
            connection,
            branch_id=branch_id,
            event_id=event_id,
            ticket_id=ticket_id,
            channel=channel,
            kind=kind,
        )
    return event_id


async def activate_if_due(connection: AsyncConnection, ticket_id: UUID) -> None:
    result = await connection.execute(
        text(
            """
            UPDATE tickets
            SET status = 'waiting', updated_at = clock_timestamp(), version = version + 1
            WHERE id = :ticket_id AND status = 'booked' AND eligible_at <= clock_timestamp()
            RETURNING branch_id, version
            """
        ),
        {"ticket_id": ticket_id},
    )
    activated = result.mappings().one_or_none()
    if activated:
        await add_ticket_event(
            connection,
            branch_id=activated["branch_id"],
            ticket_id=ticket_id,
            version=activated["version"],
            action="activated",
            old_status="booked",
            new_status="waiting",
            before_state={"status": "booked"},
            after_state={"status": "waiting"},
        )


async def ticket_response(
    connection: AsyncConnection,
    ticket_id: UUID,
    raw_token: str,
    *,
    include_token: bool = False,
) -> TicketResponse:
    result = await connection.execute(
        text(
            """
            SELECT t.id, t.branch_id, t.service_id, t.ticket_number, t.source, t.status,
                   t.scheduled_time, t.eligible_at, t.created_at, t.updated_at, t.queue_sequence,
                   w.number AS window_number, b.name AS branch_name, b.address AS branch_address,
                   b.timezone AS branch_timezone,
                   s.name AS service_name, bs.average_service_seconds
            FROM tickets t
            JOIN client_sessions cs ON cs.id = t.session_id
            JOIN branches b ON b.id = t.branch_id
            JOIN services s ON s.id = t.service_id
            JOIN branch_services bs ON bs.branch_id = t.branch_id AND bs.service_id = t.service_id
            LEFT JOIN windows w ON w.id = t.window_id AND w.branch_id = t.branch_id
            WHERE t.id = :ticket_id AND cs.token_hash = :token_hash
              AND cs.expires_at > clock_timestamp()
            """
        ),
        {"ticket_id": ticket_id, "token_hash": token_hash(raw_token)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "ticket_not_found", "Ticket was not found")

    position: int | None = None
    estimated_wait: int | None = None
    if row["status"] == "waiting":
        rule = (
            await connection.execute(
                text(
                    """
                    SELECT version, config FROM priority_rules
                    WHERE branch_id = :branch_id AND active
                    ORDER BY version DESC LIMIT 1
                    """
                ),
                {"branch_id": row["branch_id"]},
            )
        ).mappings().one_or_none()
        if rule is None:
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "priority_rule_missing",
                "Queue priority rule is unavailable",
            )
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
        position = int(
            await connection.scalar(
                text(
                    bind_priority_sql(
                        """
                    WITH ranked AS (
                        SELECT candidate.id, candidate.eligible_at, candidate.queue_sequence,
                               /* PRIORITY_EXPRESSION */ AS priority_level
                        FROM tickets candidate
                        WHERE candidate.branch_id = :branch_id
                          AND candidate.service_id = :service_id
                          AND candidate.status = 'waiting'
                    ), current_ticket AS (
                        SELECT priority_level, eligible_at, queue_sequence, id
                        FROM ranked WHERE id = :ticket_id
                    )
                    SELECT count(*) FROM ranked, current_ticket
                    WHERE (ranked.priority_level, ranked.eligible_at, ranked.queue_sequence, ranked.id)
                       <= (current_ticket.priority_level, current_ticket.eligible_at,
                           current_ticket.queue_sequence, current_ticket.id)
                    """,
                        "candidate",
                    )
                ),
                {
                    "branch_id": row["branch_id"],
                    "service_id": row["service_id"],
                    "ticket_id": row["id"],
                    **priority_parameters(config),
                },
            )
            or 0
        )
        active_ahead = int(
            await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM tickets
                    WHERE branch_id = :branch_id AND service_id = :service_id
                      AND status IN ('called', 'serving')
                    """
                ),
                {"branch_id": row["branch_id"], "service_id": row["service_id"]},
            )
            or 0
        )
        open_windows = int(
            await connection.scalar(
                text(
                    """
                    SELECT count(DISTINCT w.id)
                    FROM windows w
                    JOIN window_services ws ON ws.branch_id = w.branch_id AND ws.window_id = w.id
                    WHERE w.branch_id = :branch_id AND ws.service_id = :service_id
                      AND w.status = 'open'
                    """
                ),
                {"branch_id": row["branch_id"], "service_id": row["service_id"]},
            )
            or 0
        )
        recent_average_seconds = await connection.scalar(
            text(
                """
                SELECT avg(duration_seconds) FROM (
                    SELECT extract(epoch FROM (closed_at - service_started_at)) AS duration_seconds
                    FROM tickets
                    WHERE branch_id = :branch_id AND service_id = :service_id
                      AND status = 'served' AND service_started_at IS NOT NULL
                      AND closed_at > service_started_at
                    ORDER BY closed_at DESC LIMIT 20
                ) recent
                """
            ),
            {"branch_id": row["branch_id"], "service_id": row["service_id"]},
        )
        service_seconds = float(recent_average_seconds or row["average_service_seconds"])
        service_seconds = min(max(service_seconds, 60), 7200)
        work_ahead = max(position - 1, 0) + active_ahead
        estimated_wait = math.ceil(
            work_ahead * service_seconds / max(open_windows, 1) / 60
        )
        if position <= 2:
            latest_event_id = await connection.scalar(
                text(
                    """
                    SELECT id FROM ticket_events
                    WHERE branch_id = :branch_id AND ticket_id = :ticket_id
                    ORDER BY ticket_version DESC LIMIT 1
                    """
                ),
                {"branch_id": row["branch_id"], "ticket_id": row["id"]},
            )
            if latest_event_id is not None:
                await enqueue_ticket_notification(
                    connection,
                    branch_id=row["branch_id"],
                    event_id=latest_event_id,
                    ticket_id=row["id"],
                    channel="demo_approaching",
                    kind="queue_approaching",
                    extra_payload={"position": position},
                )

    return TicketResponse(
        **{key: row[key] for key in (
            "id", "branch_id", "service_id", "ticket_number", "source", "status",
            "scheduled_time", "created_at", "updated_at", "window_number", "branch_name",
            "branch_address", "branch_timezone", "service_name",
        )},
        position=position,
        estimated_wait_minutes=estimated_wait,
        session_token=raw_token if include_token else None,
    )


def idempotency_body(response: TicketResponse) -> dict[str, Any]:
    body = response.model_dump(mode="json")
    body["session_token"] = None
    return body


def restore_replay_token(body: dict[str, Any], raw_token: str) -> TicketResponse:
    return TicketResponse.model_validate({**body, "session_token": raw_token})
