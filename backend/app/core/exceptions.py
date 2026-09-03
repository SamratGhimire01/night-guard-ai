from fastapi import Request, status
from fastapi.responses import JSONResponse


class NightGuardError(Exception):
    """Base class for all application-raised errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_type: str = "internal_error"

    def __init__(self, message: str = "An unexpected error occurred."):
        self.message = message
        super().__init__(message)


class ServiceUnavailableError(NightGuardError):
    """Raised when a required upstream dependency (e.g. the database) is unreachable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_type = "service_unavailable"


class NotFoundError(NightGuardError):
    """Raised when a requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_type = "not_found"


class ConflictError(NightGuardError):
    """Raised when a request conflicts with existing state (e.g. duplicate email)."""

    status_code = status.HTTP_409_CONFLICT
    error_type = "conflict"


class UnauthorizedError(NightGuardError):
    """Raised when credentials or a token are missing, invalid, or expired."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_type = "unauthorized"


class ForbiddenError(NightGuardError):
    """Raised when an authenticated user's role does not permit the action."""

    status_code = status.HTTP_403_FORBIDDEN
    error_type = "forbidden"


class TooManyRequestsError(NightGuardError):
    """Raised when a client exceeds a rate limit (e.g. login attempts)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_type = "too_many_requests"


async def night_guard_exception_handler(request: Request, exc: NightGuardError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": exc.error_type, "message": exc.message}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"type": "internal_error", "message": "An unexpected error occurred."}},
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(NightGuardError, night_guard_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
