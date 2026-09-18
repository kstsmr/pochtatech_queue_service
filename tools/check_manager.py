#!/usr/bin/env python3
import sys
from datetime import date, timedelta
from urllib.parse import urlencode
from uuid import uuid4

from check_staff import BASE_URL, auth, expect_http_status, load_staff_pin, post, request


def login(branch_id: str, code: str, pin: str) -> dict:
    return request(
        "/api/staff/login",
        method="POST",
        body={"branch_id": branch_id, "employee_code": code, "pin": pin},
    )[1]


def priority_payload(config: dict) -> dict:
    return {
        "early_minutes": config["early_minutes"],
        "grace_minutes": config["grace_minutes"],
        "prebooking_max_wait_minutes": config["max_wait_minutes"]["prebooking"],
        "qr_max_wait_minutes": config["max_wait_minutes"]["qr"],
        "walk_in_max_wait_minutes": config["max_wait_minutes"]["walk_in"],
        "appointment_level": config["levels"]["appointment"],
        "qr_level": config["levels"]["qr"],
        "walk_in_level": config["levels"]["walk_in"],
        "late_prebooking_level": config["levels"]["late_prebooking"],
    }


def main() -> None:
    pin = load_staff_pin()
    _, branches = request("/api/branches")
    branch = branches[-1]
    manager = login(branch["id"], "manager-1", pin)
    operator = login(branch["id"], "operator-1", pin)
    manager_headers = auth(manager["token"])
    operator_headers = auth(operator["token"])

    if manager["role"] != "manager":
        raise AssertionError("manager-1 did not receive the manager role")
    expect_http_status("/api/manager/dashboard", 403, headers=operator_headers)
    expect_http_status("/api/staff/queue", 403, headers=manager_headers)

    _, dashboard = request("/api/manager/dashboard", headers=manager_headers)
    required = {"metrics", "recommendation", "windows", "queue", "services", "deviations", "unfinished_tickets", "priority_rule"}
    missing = required - dashboard.keys()
    if missing:
        raise AssertionError(f"manager dashboard is missing fields: {sorted(missing)}")
    metrics = dashboard["metrics"]
    if metrics["open_windows"] > metrics["total_windows"]:
        raise AssertionError("open window count exceeds total window count")

    future_service = next(item for item in dashboard["services"] if item["active"])
    future_slots = []
    for offset in range(30, 41):
        query = urlencode({
            "service_id": future_service["id"],
            "date": (date.today() + timedelta(days=offset)).isoformat(),
        })
        _, future_slots = request(f"/api/branches/{branch['id']}/slots?{query}")
        if future_slots:
            break
    if not future_slots:
        raise AssertionError("future slot is required for manager queue separation check")
    _, future_ticket = request(
        "/api/bookings",
        method="POST",
        headers={"Idempotency-Key": str(uuid4())},
        body={
            "branch_id": branch["id"],
            "service_id": future_service["id"],
            "slot_id": future_slots[0]["id"],
        },
    )
    try:
        _, with_future = request("/api/manager/dashboard", headers=manager_headers)
        if any(item["id"] == future_ticket["id"] for item in with_future["queue"]):
            raise AssertionError("future booking leaked into the live queue")
        if not any(item["id"] == future_ticket["id"] for item in with_future["unfinished_tickets"]):
            raise AssertionError("future booking is missing from unfinished tickets")
    finally:
        request(
            f"/api/tickets/{future_ticket['id']}/cancel",
            method="POST",
            headers={
                "X-Session-Token": future_ticket["session_token"],
                "Idempotency-Key": str(uuid4()),
            },
        )

    service = dashboard["services"][0]
    request(
        f"/api/manager/services/{service['id']}", method="PUT", headers=manager_headers,
        body={"active": service["active"], "average_service_seconds": service["average_service_seconds"]},
    )

    closed_window = next((item for item in dashboard["windows"] if item["status"] == "closed"), None)
    if closed_window is None:
        raise AssertionError("a closed window is required for the manager settings check")
    service_ids = closed_window["service_ids"] or [item["id"] for item in dashboard["services"] if item["active"]]
    request(
        f"/api/manager/windows/{closed_window['id']}/services", method="PUT", headers=manager_headers,
        body={"service_ids": service_ids},
    )

    original_priority = dashboard["priority_rule"]
    _, next_priority = request(
        "/api/manager/priority", method="PUT", headers=manager_headers,
        body=priority_payload(original_priority["config"]),
    )
    if next_priority["version"] <= original_priority["version"]:
        raise AssertionError("priority update did not create a new version")

    incident = post(
        "/api/staff/incidents", operator["token"],
        {"category": "operational", "description": "Automated manager dashboard check", "window_id": None, "ticket_id": None},
    )
    _, resolved = request(
        f"/api/manager/incidents/{incident['id']}/resolve",
        method="POST", headers=manager_headers,
    )
    if resolved != {"success": True}:
        raise AssertionError("incident was not resolved")

    post("/api/staff/logout", manager["token"])
    post("/api/staff/logout", operator["token"])
    print(
        "Manager smoke test passed: role isolation, live dashboard, future booking separation, "
        "metrics, services, closed-window settings, versioned priority, incident resolution, logout"
    )


if __name__ == "__main__":
    sys.exit(main())
