from urllib.parse import urlsplit

from fastapi import Request, Response

from app.core.config import settings


def origin(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def websocket_origin_allowed(value: str | None) -> bool:
    if value is None:
        return True
    allowed = {item for candidate in settings.allowed_origins if (item := origin(candidate))}
    client_origin = origin(str(settings.public_client_url))
    if client_origin:
        allowed.add(client_origin)
    return origin(value) in allowed


async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response
