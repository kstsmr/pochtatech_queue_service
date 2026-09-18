from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.api.integration_routes import router as integration_router
from app.api.manager_routes import router as manager_router
from app.api.realtime_routes import router as realtime_router
from app.api.staff_routes import router as staff_router
from app.core.config import settings
from app.core.errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from app.core.logging import configure_logging
from app.core.rate_limit import close_rate_limiter
from app.core.security import security_headers
from app.db.session import close_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    yield
    await close_rate_limiter()
    await close_engine()


app = FastAPI(
    title="Digital Queue API",
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.middleware("http")(security_headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Session-Token"],
)
app.include_router(router)
app.include_router(integration_router)
app.include_router(staff_router)
app.include_router(manager_router)
app.include_router(realtime_router)
