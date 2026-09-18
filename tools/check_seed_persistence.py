#!/usr/bin/env python3
import subprocess
import sys

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
        closed_window = next((item for item in dashboard["windows"] if item["status"] == "closed"), None)
        if len(active_services) >= 2 and closed_window is not None:
            selected = (manager, dashboard, active_services, closed_window)
            break
        request("/api/staff/logout", method="POST", headers=headers)

    if selected is None:
        raise AssertionError("a closed window and two active services are required")

    manager, dashboard, active_services, window = selected
    headers = auth(manager["token"])
    service = active_services[0]
    original_duration = service["average_service_seconds"]
    original_window_services = window["service_ids"]
    changed_duration = original_duration + 60 if original_duration < 7140 else original_duration - 60
    changed_window_services = [active_services[1]["id"]]

    try:
        request(
            f"/api/manager/services/{service['id']}",
            method="PUT",
            headers=headers,
            body={"active": True, "average_service_seconds": changed_duration},
        )
        request(
            f"/api/manager/windows/{window['id']}/services",
            method="PUT",
            headers=headers,
            body={"service_ids": changed_window_services},
        )
        subprocess.run(
            ["docker", "compose", "exec", "-T", "backend", "python", "-m", "app.db.seed"],
            check=True,
        )
        _, after_seed = request("/api/manager/dashboard", headers=headers)
        persisted_service = next(item for item in after_seed["services"] if item["id"] == service["id"])
        persisted_window = next(item for item in after_seed["windows"] if item["id"] == window["id"])
        if persisted_service["average_service_seconds"] != changed_duration:
            raise AssertionError("seed overwrote the manager service duration")
        if persisted_window["service_ids"] != changed_window_services:
            raise AssertionError("seed overwrote the manager window services")
    finally:
        request(
            f"/api/manager/services/{service['id']}",
            method="PUT",
            headers=headers,
            body={"active": True, "average_service_seconds": original_duration},
        )
        request(
            f"/api/manager/windows/{window['id']}/services",
            method="PUT",
            headers=headers,
            body={"service_ids": original_window_services},
        )
        request("/api/staff/logout", method="POST", headers=headers)

    print("Seed persistence smoke test passed: manager service and window settings were preserved")


if __name__ == "__main__":
    sys.exit(main())
