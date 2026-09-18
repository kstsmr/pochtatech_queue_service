import hashlib
import ipaddress
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from fastapi import Request, status

from app.core.config import settings
from app.core.errors import ApiError


_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

_client = redis.from_url(str(settings.redis_url), decode_responses=True)


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_identifier(request: Request) -> str:
    peer = _valid_ip(request.client.host) if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer is not None:
        peer_address = ipaddress.ip_address(peer)
        if peer_address.is_private or peer_address.is_loopback:
            candidate = _valid_ip(forwarded.split(",")[-1])
            if candidate is not None:
                return candidate
    return peer or "unknown"


async def enforce_rate_limit(request: Request, *, scope: str, limit: int) -> None:
    identifier_hash = hashlib.sha256(client_identifier(request).encode()).hexdigest()[:32]
    key = f"rate-limit:{scope}:{identifier_hash}"
    try:
        current, ttl = await _client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            settings.rate_limit_window_seconds,
        )
    except redis.RedisError as error:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "rate_limiter_unavailable",
            "Request protection is temporarily unavailable",
        ) from error
    if int(current) > limit:
        retry_after = max(1, int(ttl))
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limit_exceeded",
            "Too many requests. Try again later",
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(scope: str, limit: int) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        await enforce_rate_limit(request, scope=scope, limit=limit)

    return dependency


limit_staff_login = rate_limit("staff-login", settings.staff_login_rate_limit)
limit_ticket_write = rate_limit("ticket-write", settings.ticket_write_rate_limit)
limit_integration = rate_limit("integration", settings.integration_rate_limit)


async def close_rate_limiter() -> None:
    await _client.aclose()
