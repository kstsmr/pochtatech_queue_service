#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"


def local_env_value(name: str) -> str | None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == name:
            return value.strip().strip("'\"")
    return None


API_KEY = os.environ.get("DEMO_MOBILE_APP_API_KEY") or local_env_value("DEMO_MOBILE_APP_API_KEY")


def request(
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    authorized: bool = False,
    extra_headers: dict[str, str] | None = None,
):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if authorized and API_KEY:
        headers["X-Integration-Key"] = API_KEY
    headers.update(extra_headers or {})
    req = Request(f"{BASE_URL}{path}", data=payload, headers=headers, method=method)
    with urlopen(req, timeout=5) as response:
        return response.status, json.load(response)


def main() -> None:
    if not API_KEY:
        raise SystemExit("DEMO_MOBILE_APP_API_KEY is required")

    _, branches = request("/api/branches")
    branch = branches[0]
    _, services = request(f"/api/branches/{branch['id']}/services")
    service = services[0]

    slots = []
    for offset in range(1, 15):
        query = urlencode({"service_id": service["id"], "date": (date.today() + timedelta(days=offset)).isoformat()})
        _, slots = request(f"/api/branches/{branch['id']}/slots?{query}")
        if len(slots) >= 2:
            break
    if len(slots) < 2:
        raise AssertionError("two appointment slots are required for the integration test")

    external_id = f"demo-{uuid4()}"
    payload = {
        "external_booking_id": external_id,
        "branch_id": branch["id"],
        "service_id": service["id"],
        "slot_id": slots[0]["id"],
    }

    try:
        request("/api/integrations/demo-mobile/prebookings", method="POST", body=payload)
    except HTTPError as error:
        if error.code != 401:
            raise
    else:
        raise AssertionError("integration endpoint accepted a request without credentials")

    status_code, ticket = request(
        "/api/integrations/demo-mobile/prebookings",
        method="POST",
        body=payload,
        authorized=True,
    )
    assert (status_code, ticket["source"], ticket["status"]) == (201, "prebooking", "booked")

    _, replay = request(
        "/api/integrations/demo-mobile/prebookings",
        method="POST",
        body=payload,
        authorized=True,
    )
    assert replay["id"] == ticket["id"]
    assert replay["session_token"] == ticket["session_token"]

    deliveries = []
    for _ in range(30):
        _, deliveries = request(
            f"/api/integrations/demo-notifications/{ticket['id']}",
            authorized=True,
        )
        if any(item["status"] == "sent" for item in deliveries):
            break
        time.sleep(0.1)
    if not any(item["status"] == "sent" for item in deliveries):
        raise AssertionError(f"demo notification was not delivered: {deliveries}")

    conflicting_payload = {**payload, "slot_id": slots[1]["id"]}
    try:
        request(
            "/api/integrations/demo-mobile/prebookings",
            method="POST",
            body=conflicting_payload,
            authorized=True,
        )
    except HTTPError as error:
        if error.code != 409:
            raise
    else:
        raise AssertionError("changed duplicate integration event was not rejected")

    request(
        f"/api/tickets/{ticket['id']}/cancel",
        method="POST",
        extra_headers={
            "X-Session-Token": ticket["session_token"],
            "Idempotency-Key": str(uuid4()),
        },
    )

    print(
        "Integration smoke test passed: auth, prebooking sync, replay, "
        "conflict protection and durable notification delivery"
    )


if __name__ == "__main__":
    main()
