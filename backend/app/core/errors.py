from typing import Any, Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details
        self.headers = headers


def payload(error_code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error_code": error_code, "message": message}
    if details is not None:
        body["details"] = details
    return body


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=payload(exc.error_code, exc.message, exc.details),
        headers=exc.headers,
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    return JSONResponse(status_code=exc.status_code, content=payload(code, str(exc.detail)))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    public_errors = [
        {key: value for key, value in item.items() if key in {"type", "loc", "msg", "url"}}
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=payload("validation_error", "Request validation failed", public_errors),
    )
