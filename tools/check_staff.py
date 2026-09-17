#!/usr/bin/env python3
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"


def load_staff_pin() -> str:
    from_environment = os.environ.get("DEMO_STAFF_PIN")
    if from_environment:
        return from_environment
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEMO_STAFF_PIN="):
                value = line.partition("=")[2].strip()
                if value:
                    return value
    raise RuntimeError("Set DEMO_STAFF_PIN in the environment or local .env")


def request(path: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    req = Request(f"{BASE_URL}{path}", data=payload, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        body_text = error.read().decode()
        raise AssertionError(f"{method} {path} failed with {error.code}: {body_text}") from error


def expect_http_status(
    path: str, expected: int, *, method: str = "GET", body: dict | None = None,
    headers: dict | None = None,
) -> None:
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    req = Request(f"{BASE_URL}{path}", data=payload, headers=request_headers, method=method)
    try:
        urlopen(req, timeout=10)
    except HTTPError as error:
        if error.code == expected:
            return
        raise AssertionError(f"{method} {path}: expected HTTP {expected}, got {error.code}") from error
    raise AssertionError(f"{method} {path}: expected HTTP {expected}, request succeeded")


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def post(path: str, token: str, body: dict | None = None, extra_headers: dict | None = None):
    return request(path, method="POST", body=body, headers={**auth(token), **(extra_headers or {})})[1]


def main() -> None:
    staff_pin = load_staff_pin()
    _, branches = request("/api/branches")
    branch = branches[-1]
    _, services = request(f"/api/branches/{branch['id']}/services")
    service_ids = [service["id"] for service in services]

    expect_http_status(
        "/api/staff/login", 401, method="POST",
        body={"branch_id": branch["id"], "employee_code": f"unknown-{uuid4().hex[:6]}", "pin": staff_pin},
    )

    def login(code: str):
        return request(
            "/api/staff/login",
            method="POST",
            body={"branch_id": branch["id"], "employee_code": code, "pin": staff_pin},
        )[1]

    session_1 = login("operator-1")
    session_2 = login("operator-2")
    token_1 = session_1["token"]
    token_2 = session_2["token"]
    _, windows = request("/api/staff/windows", headers=auth(token_1))
    closed = [window for window in windows if window["status"] == "closed"]
    if len(closed) < 2:
        raise AssertionError("two closed windows are required; finish an earlier operator session first")
    window_1, window_2 = closed[:2]

    post(f"/api/staff/windows/{window_1['id']}/open", token_1, {"service_ids": service_ids})
    post(f"/api/staff/windows/{window_2['id']}/open", token_2, {"service_ids": service_ids})

    repeated_key = str(uuid4())
    first_walk_in = post(
        "/api/staff/walk-ins",
        token_1,
        {"service_id": service_ids[0]},
        {"Idempotency-Key": repeated_key},
    )
    replayed_walk_in = post(
        "/api/staff/walk-ins",
        token_1,
        {"service_id": service_ids[0]},
        {"Idempotency-Key": repeated_key},
    )
    assert_equal(replayed_walk_in["id"], first_walk_in["id"], "walk-in idempotency")
    for _ in range(2):
        post(
            "/api/staff/walk-ins",
            token_1,
            {"service_id": service_ids[0]},
            {"Idempotency-Key": str(uuid4())},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [
            executor.submit(post, f"/api/staff/windows/{window_1['id']}/call-next", token_1),
            executor.submit(post, f"/api/staff/windows/{window_2['id']}/call-next", token_2),
        ]
        called_1, called_2 = [future.result() for future in calls]
    if called_1["id"] == called_2["id"]:
        raise AssertionError("two windows received the same ticket")
    assert_equal((called_1["status"], called_2["status"]), ("called", "called"), "concurrent calls")

    post(f"/api/staff/tickets/{called_1['id']}/start", token_1)
    draining = post(f"/api/staff/windows/{window_1['id']}/close", token_1)
    assert_equal(draining["status"], "draining", "closing a busy window")
    post(f"/api/staff/tickets/{called_1['id']}/complete", token_1)
    _, windows_after_complete = request("/api/staff/windows", headers=auth(token_1))
    finished_window = next(item for item in windows_after_complete if item["id"] == window_1["id"])
    assert_equal(finished_window["status"], "closed", "draining window finalization")

    post(f"/api/staff/windows/{window_1['id']}/open", token_1, {"service_ids": service_ids})
    redirected = post(
        f"/api/staff/tickets/{called_2['id']}/redirect",
        token_2,
        {"service_id": None, "target_window_id": window_1["id"]},
    )
    assert_equal((redirected["status"], redirected["target_window_id"]), ("waiting", window_1["id"]), "redirect")
    post(f"/api/staff/windows/{window_1['id']}/close", token_1)
    _, queue_after_close = request("/api/staff/queue", headers=auth(token_2))
    released = next(item for item in queue_after_close if item["id"] == called_2["id"])
    assert_equal(released["target_window_id"], None, "target release after window close")
    post(f"/api/staff/windows/{window_1['id']}/open", token_1, {"service_ids": service_ids})
    redirected_call = post(f"/api/staff/windows/{window_1['id']}/call-next", token_1)
    assert_equal(redirected_call["id"], called_2["id"], "directed ticket selection")
    post(f"/api/staff/tickets/{called_2['id']}/start", token_1)
    post(f"/api/staff/tickets/{called_2['id']}/complete", token_1)

    returned_call = post(f"/api/staff/windows/{window_2['id']}/call-next", token_2)
    returned = post(f"/api/staff/tickets/{returned_call['id']}/return", token_2)
    assert_equal((returned["status"], returned["return_count"]), ("waiting", 1), "return to queue")
    called_again = post(f"/api/staff/windows/{window_2['id']}/call-next", token_2)
    assert_equal(called_again["id"], returned_call["id"], "returned ticket selection")
    post(f"/api/staff/tickets/{called_again['id']}/recall", token_2)
    post(f"/api/staff/tickets/{called_again['id']}/start", token_2)
    post(f"/api/staff/tickets/{called_again['id']}/complete", token_2)

    post(
        "/api/staff/walk-ins", token_2, {"service_id": service_ids[0]},
        {"Idempotency-Key": str(uuid4())},
    )
    no_show_called = post(f"/api/staff/windows/{window_2['id']}/call-next", token_2)
    no_show = post(f"/api/staff/tickets/{no_show_called['id']}/no-show", token_2)
    assert_equal(no_show["status"], "no_show", "no-show transition")

    incident = post(
        "/api/staff/incidents",
        token_2,
        {"category": "technical", "description": "Automated operator workplace check", "window_id": window_2["id"], "ticket_id": None},
    )
    assert_equal(incident["category"], "technical", "incident")

    post(f"/api/staff/windows/{window_1['id']}/close", token_1)
    post(f"/api/staff/windows/{window_2['id']}/close", token_2)
    post("/api/staff/logout", token_1)
    post("/api/staff/logout", token_2)
    expect_http_status("/api/staff/queue", 401, headers=auth(token_1))
    print("Staff smoke test passed: accounts, windows, idempotent walk-in, concurrent call, draining, redirect release, return, recall, no-show, complete, incident, logout")


if __name__ == "__main__":
    main()
