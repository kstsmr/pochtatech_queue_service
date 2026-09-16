#!/usr/bin/env python3
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"


def request(path: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    req = Request(f"{BASE_URL}{path}", data=payload, headers=request_headers, method=method)
    with urlopen(req, timeout=5) as response:
        return response.status, json.load(response)


def request_bytes(path: str):
    req = Request(f"{BASE_URL}{path}", headers={"Accept": "image/svg+xml"})
    with urlopen(req, timeout=5) as response:
        return response.status, response.headers.get_content_type(), response.read()


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def main() -> None:
    status, health = request("/api/health")
    assert_equal((status, health["status"]), (200, "ok"), "health check")

    _, branches = request("/api/branches")
    branch = branches[0]
    _, branch_by_code = request(f"/api/branches/code/{branch['postal_code']}")
    assert_equal(branch_by_code["id"], branch["id"], "branch lookup")
    _, qr_info = request(f"/api/branches/{branch['id']}/queue-qr")
    scanned_query = parse_qs(urlparse(qr_info["join_url"]).query)
    assert_equal(scanned_query, {"branch": [branch["postal_code"]]}, "QR deep-link")
    assert_equal(qr_info["qr_svg_path"], f"/api/branches/{branch['id']}/queue-qr.svg", "QR image path")
    qr_status, qr_content_type, qr_svg = request_bytes(f"/api/branches/{branch['id']}/queue-qr.svg")
    assert_equal((qr_status, qr_content_type), (200, "image/svg+xml"), "branch QR response")
    if not qr_svg.startswith(b"<svg") or len(qr_svg) < 500:
        raise AssertionError("branch QR is not a valid non-empty SVG")

    _, services = request(f"/api/branches/{branch['id']}/services")
    service = services[0]
    visit_date = date.today() + timedelta(days=1)
    query = urlencode({"service_id": service["id"], "date": visit_date.isoformat()})
    _, slots = request(f"/api/branches/{branch['id']}/slots?{query}")
    if not slots:
        raise AssertionError("appointment slots are empty")

    booking_key = str(uuid4())
    booking_headers = {"Idempotency-Key": booking_key}
    booking_body = {"branch_id": branch["id"], "service_id": service["id"], "slot_id": slots[0]["id"]}
    status, booking = request("/api/bookings", method="POST", body=booking_body, headers=booking_headers)
    assert_equal((status, booking["status"], booking["source"]), (201, "booked", "prebooking"), "booking")
    _, booking_replay = request("/api/bookings", method="POST", body=booking_body, headers=booking_headers)
    assert_equal(booking_replay["id"], booking["id"], "booking idempotency")
    assert_equal(booking_replay["session_token"], booking["session_token"], "booking token replay")

    token_headers = {"X-Session-Token": booking["session_token"]}
    _, restored = request(f"/api/tickets/{booking['id']}", headers=token_headers)
    assert_equal(restored["id"], booking["id"], "ticket restore")
    cancel_headers = {**token_headers, "Idempotency-Key": str(uuid4())}
    _, cancelled = request(f"/api/tickets/{booking['id']}/cancel", method="POST", headers=cancel_headers)
    assert_equal(cancelled["status"], "cancelled", "booking cancellation")

    qr_key = str(uuid4())
    qr_headers = {"Idempotency-Key": qr_key}
    qr_body = {"branch_code": branch["postal_code"], "service_id": service["id"]}
    status, qr_ticket = request("/api/queue/join", method="POST", body=qr_body, headers=qr_headers)
    assert_equal((status, qr_ticket["status"], qr_ticket["source"]), (201, "waiting", "qr"), "QR join")
    _, qr_replay = request("/api/queue/join", method="POST", body=qr_body, headers=qr_headers)
    assert_equal(qr_replay["id"], qr_ticket["id"], "QR idempotency")
    qr_cancel_headers = {"X-Session-Token": qr_ticket["session_token"], "Idempotency-Key": str(uuid4())}
    _, qr_cancelled = request(
        f"/api/tickets/{qr_ticket['id']}/cancel", method="POST", headers=qr_cancel_headers
    )
    assert_equal(qr_cancelled["status"], "cancelled", "QR cancellation")

    concurrent_key = str(uuid4())
    concurrent_headers = {"Idempotency-Key": concurrent_key}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(request, "/api/queue/join", method="POST", body=qr_body, headers=concurrent_headers)
            for _ in range(2)
        ]
        concurrent_tickets = [future.result()[1] for future in futures]
    assert_equal(concurrent_tickets[0]["id"], concurrent_tickets[1]["id"], "concurrent idempotency")
    concurrent_cancel_headers = {
        "X-Session-Token": concurrent_tickets[0]["session_token"],
        "Idempotency-Key": str(uuid4()),
    }
    request(
        f"/api/tickets/{concurrent_tickets[0]['id']}/cancel",
        method="POST",
        headers=concurrent_cancel_headers,
    )

    try:
        request(f"/api/tickets/{booking['id']}", headers={"X-Session-Token": "x" * 32})
    except HTTPError as error:
        assert_equal(error.code, 404, "invalid token response")
    else:
        raise AssertionError("invalid token unexpectedly restored a ticket")

    print("API smoke test passed: health, catalog, QR image, slots, booking, QR join, restore, concurrent idempotency, cancellation")


if __name__ == "__main__":
    main()
