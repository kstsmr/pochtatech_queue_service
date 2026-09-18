#!/usr/bin/env python3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from urllib.parse import urlencode
from uuid import uuid4

from check_staff import auth, load_staff_pin, request


def main() -> None:
    pin = load_staff_pin()
    _, branches = request("/api/branches")
    selected = None

    for branch in reversed(branches):
        _, manager = request(
            "/api/staff/login",
            method="POST",
            body={"branch_id": branch["id"], "employee_code": "manager-1", "pin": pin},
        )
        headers = auth(manager["token"])
        _, dashboard = request("/api/manager/dashboard", headers=headers)
        active_services = [item for item in dashboard["services"] if item["active"]]
        if len(active_services) >= 2 and all(item["status"] == "closed" for item in dashboard["windows"]):
            selected = (branch, manager, dashboard)
            break
        request("/api/staff/logout", method="POST", headers=headers)

    if selected is None:
        raise AssertionError("a branch with closed windows is required for the service capacity check")

    branch, manager, dashboard = selected
    headers = auth(manager["token"])
    original_services = {item["id"]: item["service_ids"] for item in dashboard["windows"]}
    active_services = [item for item in dashboard["services"] if item["active"]]
    target_service = active_services[0]
    fallback_service = active_services[1]
    created_tickets = []

    try:
        for index, window in enumerate(dashboard["windows"]):
            request(
                f"/api/manager/windows/{window['id']}/services",
                method="PUT",
                headers=headers,
                body={"service_ids": [target_service["id"] if index == 0 else fallback_service["id"]]},
            )

        slots = []
        for offset in range(45, 61):
            query = urlencode({
                "service_id": target_service["id"],
                "date": (date.today() + timedelta(days=offset)).isoformat(),
            })
            _, slots = request(f"/api/branches/{branch['id']}/slots?{query}")
            if slots:
                break
        if not slots:
            raise AssertionError("no future slot found for service capacity check")
        if slots[0]["available"] != 1:
            raise AssertionError(f"service capacity must be 1, got {slots[0]['available']}")

        body = {
            "branch_id": branch["id"],
            "service_id": target_service["id"],
            "slot_id": slots[0]["id"],
        }

        def create_booking():
            try:
                return request(
                    "/api/bookings",
                    method="POST",
                    headers={"Idempotency-Key": str(uuid4())},
                    body=body,
                )
            except AssertionError as error:
                if "failed with 409" in str(error):
                    return 409, None
                raise

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: create_booking(), range(2)))
        created_tickets = [payload for status_code, payload in results if status_code == 201]
        conflicts = [status_code for status_code, _ in results if status_code == 409]
        if len(created_tickets) != 1 or len(conflicts) != 1:
            raise AssertionError(f"expected one booking and one conflict, got {results}")
    finally:
        for ticket in created_tickets:
            request(
                f"/api/tickets/{ticket['id']}/cancel",
                method="POST",
                headers={
                    "X-Session-Token": ticket["session_token"],
                    "Idempotency-Key": str(uuid4()),
                },
            )
        for window in dashboard["windows"]:
            request(
                f"/api/manager/windows/{window['id']}/services",
                method="PUT",
                headers=headers,
                body={"service_ids": original_services[window["id"]]},
            )
        request("/api/staff/logout", method="POST", headers=headers)

    print("Service capacity smoke test passed: one compatible window accepts one concurrent booking")


if __name__ == "__main__":
    sys.exit(main())
