#!/usr/bin/env python3
import json
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


FRONTEND = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000").rstrip("/")
BACKEND = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000").rstrip("/")


def call(base, path, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(f"{base}{path}", data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, _headers(response.headers), _decode(raw)
    except HTTPError as error:
        raw = error.read()
        return error.code, _headers(error.headers), _decode(raw)


def _headers(values):
    return {key.lower(): value for key, value in values.items()}


def _decode(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def expect_status(expected, result, label):
    status, _, body = result
    if status != expected:
        raise AssertionError(f"{label}: expected {expected}, got {status}: {body}")
    return body


def load_secret(name):
    with open(".env", encoding="utf-8") as env_file:
        for line in env_file:
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    raise AssertionError(f"{name} is missing from .env")


def assert_private_data_services():
    for service in ("db", "redis"):
        container_id = subprocess.run(
            ["docker", "compose", "ps", "-q", service],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        inspection = subprocess.run(
            ["docker", "inspect", container_id],
            check=True,
            capture_output=True,
            text=True,
        )
        ports = json.loads(inspection.stdout)[0]["NetworkSettings"]["Ports"]
        published = {name: bindings for name, bindings in ports.items() if bindings}
        if published:
            raise AssertionError(f"{service} unexpectedly publishes {published}")


def reset_local_login_counter():
    scan = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "redis", "redis-cli",
            "--scan", "--pattern", "rate-limit:staff-login:*",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for key in scan.stdout.splitlines():
        subprocess.run(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "DEL", key],
            check=True,
            capture_output=True,
            text=True,
        )


def main():
    created = []
    operator_headers = None
    manager_headers = None
    try:
        reset_local_login_counter()
        status, frontend_headers, _ = call(FRONTEND, "/")
        if status != 200:
            raise AssertionError(f"frontend unavailable: {status}")
        required_headers = (
            "content-security-policy",
            "x-content-type-options",
            "x-frame-options",
            "permissions-policy",
        )
        missing = [name for name in required_headers if name not in frontend_headers]
        if missing:
            raise AssertionError(f"frontend security headers missing: {missing}")
        if "/" in frontend_headers.get("server", ""):
            raise AssertionError("web server exposes a version")

        status, api_headers, health = call(BACKEND, "/api/health", headers={"Origin": "https://evil.example"})
        if status != 200 or health.get("status") != "ok":
            raise AssertionError(f"backend unavailable: {status} {health}")
        if api_headers.get("cache-control") != "no-store":
            raise AssertionError("API responses are not protected from shared caching")
        if "access-control-allow-origin" in api_headers:
            raise AssertionError("untrusted CORS origin was accepted")

        expect_status(405, call(FRONTEND, "/api/health", method="TRACE"), "TRACE method")
        _, _, traversal_body = call(FRONTEND, "/%2e%2e/%2e%2e/etc/passwd")
        if "root:x:" in str(traversal_body):
            raise AssertionError("path traversal exposed a host file")

        branches = expect_status(200, call(BACKEND, "/api/branches?limit=2"), "branch catalog")
        if len(branches) != 2:
            raise AssertionError("branch catalog limit is not enforced")
        injection = quote("' OR 1=1 --")
        injection_result = expect_status(200, call(BACKEND, f"/api/branches?query={injection}"), "SQL payload")
        if injection_result:
            raise AssertionError("SQL payload unexpectedly broadened branch search")

        branch = branches[0]
        services = expect_status(
            200,
            call(BACKEND, f"/api/branches/{branch['id']}/services"),
            "service catalog",
        )
        service = services[0]
        for _ in range(2):
            ticket = expect_status(
                201,
                call(
                    BACKEND,
                    "/api/queue/join",
                    method="POST",
                    headers={"Idempotency-Key": str(uuid4())},
                    body={"branch_code": branch["postal_code"], "service_id": service["id"]},
                ),
                "QR ticket",
            )
            created.append(ticket)

        first, second = created
        expect_status(
            404,
            call(
                BACKEND,
                f"/api/tickets/{second['id']}",
                headers={"X-Session-Token": first["session_token"]},
            ),
            "cross-ticket access",
        )

        secret_probe = "PIN-SHOULD-NEVER-BE-REFLECTED-" + "x" * 64
        status, _, validation = call(
            BACKEND,
            "/api/staff/login",
            method="POST",
            body={"branch_id": branch["id"], "employee_code": "operator-1", "pin": secret_probe},
        )
        if status != 422 or secret_probe in json.dumps(validation):
            raise AssertionError("validation response reflected sensitive input")

        expect_status(
            401,
            call(BACKEND, "/api/integrations/demo-notifications/00000000-0000-0000-0000-000000000000"),
            "integration without key",
        )
        expect_status(401, call(BACKEND, "/api/manager/dashboard"), "manager without session")

        pin = load_secret("DEMO_STAFF_PIN")
        operator = expect_status(
            200,
            call(
                BACKEND,
                "/api/staff/login",
                method="POST",
                body={"branch_id": branch["id"], "employee_code": "operator-1", "pin": pin},
            ),
            "operator login",
        )
        operator_headers = {"Authorization": f"Bearer {operator['token']}"}
        expect_status(403, call(BACKEND, "/api/manager/dashboard", headers=operator_headers), "operator RBAC")

        manager = expect_status(
            200,
            call(
                BACKEND,
                "/api/staff/login",
                method="POST",
                body={"branch_id": branch["id"], "employee_code": "manager-1", "pin": pin},
            ),
            "manager login",
        )
        manager_headers = {"Authorization": f"Bearer {manager['token']}"}
        expect_status(403, call(BACKEND, "/api/staff/windows", headers=manager_headers), "manager RBAC")

        test_ip = f"2001:db8::{uuid4().hex[:8]}"
        statuses = []
        for _ in range(21):
            status, headers, _ = call(
                BACKEND,
                "/api/staff/login",
                method="POST",
                headers={"X-Forwarded-For": test_ip},
                body={"branch_id": branch["id"], "employee_code": "missing-user", "pin": "0000"},
            )
            statuses.append(status)
        if 429 not in statuses or any(status not in {401, 429} for status in statuses):
            raise AssertionError(f"login rate limit failed: {statuses}")
        first_limited = statuses.index(429)
        if any(status != 401 for status in statuses[:first_limited]):
            raise AssertionError(f"unexpected response before rate limit: {statuses}")
        if any(status != 429 for status in statuses[first_limited:]) or "retry-after" not in headers:
            raise AssertionError(f"rate limit was not stable: {statuses}")

        assert_private_data_services()
        print("Security smoke test passed: headers, CORS, RBAC, IDOR, injection, secret handling, rate limits, private data ports")
    finally:
        for ticket in created:
            call(
                BACKEND,
                f"/api/tickets/{ticket['id']}/cancel",
                method="POST",
                headers={
                    "Idempotency-Key": str(uuid4()),
                    "X-Session-Token": ticket["session_token"],
                },
            )
        for headers in (operator_headers, manager_headers):
            if headers:
                call(BACKEND, "/api/staff/logout", method="POST", headers=headers)
        reset_local_login_counter()


if __name__ == "__main__":
    main()
