import json
import math
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas import (
    ManagerDashboardResponse,
    ManagerDeviationResponse,
    ManagerIncidentResponse,
    ManagerMetricsResponse,
    ManagerPriorityResponse,
    ManagerPriorityUpdateRequest,
    ManagerRecommendationResponse,
    ManagerServiceResponse,
    StaffWindowResponse,
)
from app.core.errors import ApiError
from app.core.priority import validate_priority_config
from app.services.staff import (
    StaffIdentity,
    add_window_event,
    list_queue,
    list_unfinished_tickets,
    list_windows,
    release_targeted_tickets,
)


async def active_priority_rule(
    connection: AsyncConnection, branch_id: UUID
) -> ManagerPriorityResponse:
    row = (
        await connection.execute(
            text(
                """
                SELECT version, config, actor_id, created_at
                FROM priority_rules
                WHERE branch_id = :branch_id AND active
                ORDER BY version DESC LIMIT 1
                """
            ),
            {"branch_id": branch_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "priority_rule_missing",
            "Queue priority rule is unavailable",
        )
    try:
        config = validate_priority_config(dict(row["config"]))
    except ValueError as error:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "priority_rule_invalid",
            "Active queue priority rule is invalid",
        ) from error
    return ManagerPriorityResponse(
        version=row["version"],
        config=config,
        actor_id=row["actor_id"],
        created_at=row["created_at"],
    )


async def list_manager_services(
    connection: AsyncConnection, branch_id: UUID
) -> list[ManagerServiceResponse]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT s.id, s.name, bs.active, bs.average_service_seconds
                FROM branch_services bs
                JOIN services s ON s.id = bs.service_id
                WHERE bs.branch_id = :branch_id
                ORDER BY s.name
                """
            ),
            {"branch_id": branch_id},
        )
    ).mappings().all()
    return [ManagerServiceResponse.model_validate(row) for row in rows]


async def _manager_metrics(
    connection: AsyncConnection, branch_id: UUID
) -> ManagerMetricsResponse:
    row = (
        await connection.execute(
            text(
                """
                WITH branch_clock AS (
                    SELECT timezone, (clock_timestamp() AT TIME ZONE timezone)::date AS local_day
                    FROM branches WHERE id = :branch_id
                ), ticket_stats AS (
                    SELECT
                        count(*) FILTER (WHERE t.status = 'waiting' OR
                            (t.status = 'booked' AND t.eligible_at <= clock_timestamp()))::int
                            AS waiting_count,
                        COALESCE(round(avg(extract(epoch FROM (t.called_at - t.eligible_at)) / 60)
                            FILTER (WHERE t.called_at IS NOT NULL AND
                                (t.called_at AT TIME ZONE bc.timezone)::date = bc.local_day), 1), 0) AS average_wait,
                        GREATEST(
                            COALESCE(max(floor(extract(epoch FROM
                                (clock_timestamp() - t.eligible_at)) / 60))
                                FILTER (WHERE t.status = 'waiting' OR
                                    (t.status = 'booked' AND t.eligible_at <= clock_timestamp())), 0),
                            COALESCE(max(floor(extract(epoch FROM (t.called_at - t.eligible_at)) / 60))
                                FILTER (WHERE t.called_at IS NOT NULL AND
                                    (t.called_at AT TIME ZONE bc.timezone)::date = bc.local_day), 0)
                        )::int AS maximum_wait,
                        count(*) FILTER (WHERE t.status = 'served' AND
                            (t.closed_at AT TIME ZONE bc.timezone)::date = bc.local_day)::int AS served_today,
                        count(*) FILTER (WHERE t.status IN ('booked', 'waiting', 'called', 'serving'))::int
                            AS unfinished_tickets
                    FROM branch_clock bc
                    LEFT JOIN tickets t ON t.branch_id = :branch_id
                    GROUP BY bc.timezone, bc.local_day
                ), window_stats AS (
                    SELECT count(*)::int AS total_windows,
                           count(*) FILTER (WHERE status IN ('open', 'draining'))::int AS open_windows
                    FROM windows WHERE branch_id = :branch_id
                ), busy_stats AS (
                    SELECT count(DISTINCT window_id)::int AS busy_windows
                    FROM tickets
                    WHERE branch_id = :branch_id AND status IN ('called', 'serving')
                ), incident_stats AS (
                    SELECT count(*)::int AS unresolved_incidents
                    FROM incidents WHERE branch_id = :branch_id AND resolved_at IS NULL
                )
                SELECT ts.*, ws.total_windows, ws.open_windows, bs.busy_windows,
                       ins.unresolved_incidents
                FROM ticket_stats ts CROSS JOIN window_stats ws
                CROSS JOIN busy_stats bs CROSS JOIN incident_stats ins
                """
            ),
            {"branch_id": branch_id},
        )
    ).mappings().one()
    load = 0.0 if row["open_windows"] == 0 else round(
        100 * row["busy_windows"] / row["open_windows"], 1
    )
    return ManagerMetricsResponse(
        waiting_count=row["waiting_count"],
        average_wait_minutes=float(row["average_wait"]),
        maximum_wait_minutes=row["maximum_wait"],
        served_today=row["served_today"],
        open_windows=row["open_windows"],
        total_windows=row["total_windows"],
        window_load_percent=load,
        unresolved_incidents=row["unresolved_incidents"],
        unfinished_tickets=row["unfinished_tickets"],
    )


async def _incidents(
    connection: AsyncConnection, branch_id: UUID
) -> list[ManagerIncidentResponse]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT i.id, i.category, i.description, i.actor_id, w.number AS window_number,
                       t.ticket_number, i.created_at
                FROM incidents i
                LEFT JOIN windows w ON w.id = i.window_id
                LEFT JOIN tickets t ON t.id = i.ticket_id
                WHERE i.branch_id = :branch_id AND i.resolved_at IS NULL
                ORDER BY i.created_at DESC LIMIT 50
                """
            ),
            {"branch_id": branch_id},
        )
    ).mappings().all()
    return [ManagerIncidentResponse.model_validate(row) for row in rows]


async def _deviations(
    connection: AsyncConnection, branch_id: UUID, config: dict[str, Any]
) -> list[ManagerDeviationResponse]:
    waits = config["max_wait_minutes"]
    rows = (
        await connection.execute(
            text(
                """
                SELECT 'ticket-' || t.id::text AS id, 'wait_limit' AS kind,
                       'Превышено время ожидания' AS label,
                       'Талон ' || t.ticket_number || ' ожидает ' ||
                           floor(extract(epoch FROM (clock_timestamp() - t.eligible_at)) / 60)::int ||
                           ' мин.' AS detail,
                       t.eligible_at AS occurred_at
                FROM tickets t
                WHERE t.branch_id = :branch_id AND t.status IN ('booked', 'waiting')
                  AND clock_timestamp() - t.eligible_at > make_interval(mins =>
                    CASE t.source WHEN 'prebooking' THEN CAST(:pre_wait AS integer)
                                  WHEN 'qr' THEN CAST(:qr_wait AS integer)
                                  ELSE CAST(:walk_wait AS integer) END)
                UNION ALL
                SELECT 'call-' || t.id::text, 'stale_call', 'Клиент долго не подходит',
                       'Талон ' || t.ticket_number || ' вызван более 5 минут назад.', t.called_at
                FROM tickets t
                WHERE t.branch_id = :branch_id AND t.status = 'called'
                  AND t.called_at < clock_timestamp() - interval '5 minutes'
                UNION ALL
                SELECT 'service-' || t.id::text, 'long_service', 'Обслуживание затянулось',
                       'Талон ' || t.ticket_number || ' обслуживается дольше планового времени.',
                       t.service_started_at
                FROM tickets t JOIN branch_services bs
                  ON bs.branch_id = t.branch_id AND bs.service_id = t.service_id
                WHERE t.branch_id = :branch_id AND t.status = 'serving'
                  AND t.service_started_at < clock_timestamp() -
                      make_interval(secs => bs.average_service_seconds * 2)
                UNION ALL
                SELECT 'incident-' || i.id::text, 'unresolved_incident', 'Открытая проблема',
                       i.description, i.created_at
                FROM incidents i
                WHERE i.branch_id = :branch_id AND i.resolved_at IS NULL
                ORDER BY occurred_at DESC LIMIT 100
                """
            ),
            {
                "branch_id": branch_id,
                "pre_wait": waits["prebooking"],
                "qr_wait": waits["qr"],
                "walk_wait": waits["walk_in"],
            },
        )
    ).mappings().all()
    return [ManagerDeviationResponse.model_validate(row) for row in rows]


def _recommendation(
    metrics: ManagerMetricsResponse, config: dict[str, Any]
) -> ManagerRecommendationResponse:
    available = max(metrics.total_windows - metrics.open_windows, 0)
    target = max(1, math.ceil(metrics.waiting_count / 4)) if metrics.waiting_count else 0
    suggested = min(available, max(target - metrics.open_windows, 0))
    threshold = min(config["max_wait_minutes"].values())
    if metrics.maximum_wait_minutes >= threshold and available:
        return ManagerRecommendationResponse(
            level="critical",
            title="Стоит открыть дополнительное окно",
            detail=f"Максимальное ожидание достигло {metrics.maximum_wait_minutes} мин.",
            suggested_windows=max(1, suggested),
        )
    if metrics.waiting_count > max(metrics.open_windows, 1) * 3 and available:
        return ManagerRecommendationResponse(
            level="attention",
            title="Очередь растёт",
            detail=f"На {metrics.open_windows} открытых окон ожидают {metrics.waiting_count} клиентов.",
            suggested_windows=max(1, suggested),
        )
    return ManagerRecommendationResponse(
        level="normal",
        title="Нагрузка штатная",
        detail="Текущий состав окон справляется с очередью.",
        suggested_windows=0,
    )


async def manager_dashboard(
    connection: AsyncConnection, identity: StaffIdentity
) -> ManagerDashboardResponse:
    priority = await active_priority_rule(connection, identity.branch_id)
    windows = await list_windows(connection, identity)
    queue = await list_queue(connection, identity)
    unfinished = await list_unfinished_tickets(connection, identity)
    services = await list_manager_services(connection, identity.branch_id)
    metrics = await _manager_metrics(connection, identity.branch_id)
    incidents = await _incidents(connection, identity.branch_id)
    deviations = await _deviations(connection, identity.branch_id, priority.config)
    return ManagerDashboardResponse(
        generated_at=datetime.now().astimezone(),
        metrics=metrics,
        recommendation=_recommendation(metrics, priority.config),
        windows=windows,
        queue=queue,
        services=services,
        incidents=incidents,
        deviations=deviations,
        unfinished_tickets=unfinished,
        priority_rule=priority,
    )


async def update_service(
    connection: AsyncConnection,
    identity: StaffIdentity,
    service_id: UUID,
    *,
    active: bool,
    average_service_seconds: int,
) -> ManagerServiceResponse:
    row = (
        await connection.execute(
            text(
                """
                UPDATE branch_services
                SET active = :active, average_service_seconds = :average_service_seconds
                WHERE branch_id = :branch_id AND service_id = :service_id
                RETURNING service_id AS id, active, average_service_seconds
                """
            ),
            {
                "branch_id": identity.branch_id,
                "service_id": service_id,
                "active": active,
                "average_service_seconds": average_service_seconds,
            },
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "branch_service_not_found", "Service was not found")
    name = await connection.scalar(text("SELECT name FROM services WHERE id = :id"), {"id": service_id})
    return ManagerServiceResponse(name=name, **row)


async def update_window_services(
    connection: AsyncConnection,
    identity: StaffIdentity,
    window_id: UUID,
    service_ids: list[UUID],
) -> StaffWindowResponse:
    if len(service_ids) != len(set(service_ids)):
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
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "window_must_be_closed",
            "Close the window before changing its services",
        )
    count = await connection.scalar(
        text(
            """
            SELECT count(*) FROM branch_services
            WHERE branch_id = :branch_id AND service_id = ANY(CAST(:ids AS uuid[])) AND active
            """
        ),
        {"branch_id": identity.branch_id, "ids": service_ids},
    )
    if count != len(service_ids):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_window_services", "Service is unavailable")
    before_ids = (
        await connection.execute(
            text("SELECT service_id FROM window_services WHERE window_id = :window_id ORDER BY service_id"),
            {"window_id": window_id},
        )
    ).scalars().all()
    await connection.execute(text("DELETE FROM window_services WHERE window_id = :window_id"), {"window_id": window_id})
    await connection.execute(
        text(
            """
            INSERT INTO window_services (branch_id, window_id, service_id)
            SELECT :branch_id, :window_id, unnest(CAST(:ids AS uuid[]))
            """
        ),
        {"branch_id": identity.branch_id, "window_id": window_id, "ids": service_ids},
    )
    version = window["version"] + 1
    await connection.execute(
        text("UPDATE windows SET version = :version WHERE id = :id"),
        {"version": version, "id": window_id},
    )
    await add_window_event(
        connection,
        branch_id=identity.branch_id,
        window_id=window_id,
        version=version,
        actor_id=identity.employee_code,
        action="services_updated",
        before_state={"status": "closed", "service_ids": [str(item) for item in before_ids]},
        after_state={"status": "closed", "service_ids": [str(item) for item in service_ids]},
    )
    return next(item for item in await list_windows(connection, identity) if item.id == window_id)


async def manager_close_window(
    connection: AsyncConnection, identity: StaffIdentity, window_id: UUID
) -> StaffWindowResponse:
    window = (
        await connection.execute(
            text("SELECT * FROM windows WHERE id = :id AND branch_id = :branch_id FOR UPDATE"),
            {"id": window_id, "branch_id": identity.branch_id},
        )
    ).mappings().one_or_none()
    if window is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "window_not_found", "Window was not found")
    if window["status"] == "closed":
        return next(item for item in await list_windows(connection, identity) if item.id == window_id)
    has_active = await connection.scalar(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM tickets WHERE branch_id = :branch_id
                AND window_id = :window_id AND status IN ('called', 'serving'))
            """
        ),
        {"branch_id": identity.branch_id, "window_id": window_id},
    )
    next_status = "draining" if has_active else "closed"
    version = window["version"] + 1
    await connection.execute(
        text(
            """
            UPDATE windows SET status = :status,
                operator_session_id = CASE WHEN :status = 'closed' THEN NULL ELSE operator_session_id END,
                version = :version WHERE id = :id
            """
        ),
        {"status": next_status, "version": version, "id": window_id},
    )
    await add_window_event(
        connection,
        branch_id=identity.branch_id,
        window_id=window_id,
        version=version,
        actor_id=identity.employee_code,
        action="manager_close_requested",
        before_state={"status": window["status"]},
        after_state={"status": next_status},
    )
    await release_targeted_tickets(connection, identity=identity, window_id=window_id)
    return next(item for item in await list_windows(connection, identity) if item.id == window_id)


async def update_priority_rule(
    connection: AsyncConnection,
    identity: StaffIdentity,
    payload: ManagerPriorityUpdateRequest,
) -> ManagerPriorityResponse:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"priority:{identity.branch_id}"},
    )
    version = int(
        await connection.scalar(
            text("SELECT COALESCE(max(version), 0) + 1 FROM priority_rules WHERE branch_id = :branch_id"),
            {"branch_id": identity.branch_id},
        )
    )
    config = {
        "schema_version": 2,
        "rule_version": version,
        "early_minutes": payload.early_minutes,
        "grace_minutes": payload.grace_minutes,
        "max_wait_minutes": {
            "prebooking": payload.prebooking_max_wait_minutes,
            "qr": payload.qr_max_wait_minutes,
            "walk_in": payload.walk_in_max_wait_minutes,
        },
        "levels": {
            "overdue": 0,
            "appointment": payload.appointment_level,
            "qr": payload.qr_level,
            "walk_in": payload.walk_in_level,
            "late_prebooking": payload.late_prebooking_level,
        },
    }
    try:
        validate_priority_config(config)
    except ValueError as error:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_priority_rule", str(error)) from error
    await connection.execute(
        text("UPDATE priority_rules SET active = false WHERE branch_id = :branch_id AND active"),
        {"branch_id": identity.branch_id},
    )
    created_at = await connection.scalar(
        text(
            """
            INSERT INTO priority_rules (branch_id, version, config, actor_id)
            VALUES (:branch_id, :version, CAST(:config AS jsonb), :actor_id)
            RETURNING created_at
            """
        ),
        {
            "branch_id": identity.branch_id,
            "version": version,
            "config": json.dumps(config),
            "actor_id": identity.employee_code,
        },
    )
    return ManagerPriorityResponse(
        version=version,
        config=config,
        actor_id=identity.employee_code,
        created_at=created_at,
    )


async def resolve_incident(
    connection: AsyncConnection, identity: StaffIdentity, incident_id: UUID
) -> None:
    result = await connection.execute(
        text(
            """
            UPDATE incidents SET resolved_at = clock_timestamp()
            WHERE id = :id AND branch_id = :branch_id AND resolved_at IS NULL
            """
        ),
        {"id": incident_id, "branch_id": identity.branch_id},
    )
    if result.rowcount != 1:
        raise ApiError(status.HTTP_404_NOT_FOUND, "incident_not_found", "Open incident was not found")
