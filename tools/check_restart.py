#!/usr/bin/env python3
import json
import subprocess
import sys
import time
from http.client import HTTPException
from urllib.error import URLError
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


def wait_until_healthy(timeout_seconds: float = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, body = request("/api/health")
            if status == 200 and body.get("status") == "ok":
                return
        except (URLError, HTTPException, OSError):
            pass
        time.sleep(0.5)
    raise AssertionError("backend did not become healthy after restart")


def main() -> None:
    _, branches = request("/api/branches")
    branch = branches[0]
    _, services = request(f"/api/branches/{branch['id']}/services")
    service = services[0]
    _, ticket = request(
        "/api/queue/join",
        method="POST",
        headers={"Idempotency-Key": str(uuid4())},
        body={"branch_code": branch["postal_code"], "service_id": service["id"]},
    )
    token_headers = {"X-Session-Token": ticket["session_token"]}
    try:
        subprocess.run(
            ["docker", "compose", "restart", "backend"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        wait_until_healthy()
        _, restored = request(f"/api/tickets/{ticket['id']}", headers=token_headers)
        if restored["id"] != ticket["id"] or restored["status"] != "waiting":
            raise AssertionError("ticket state was not restored after backend restart")
    finally:
        wait_until_healthy()
        request(
            f"/api/tickets/{ticket['id']}/cancel",
            method="POST",
            headers={**token_headers, "Idempotency-Key": str(uuid4())},
        )
    print("Restart smoke test passed: active ticket persisted and session was restored")


if __name__ == "__main__":
    main()
