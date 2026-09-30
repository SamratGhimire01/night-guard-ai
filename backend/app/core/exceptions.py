import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


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


class PlanRequiredError(NightGuardError):
    """Raised when an authenticated, tenant-scoped action requires a higher
    subscription plan than the business currently has (Phase 34). 402 Payment
    Required is the real, standard HTTP status for exactly this case — never
    403 (that's for "not your data/role"), since a plan gap is honestly
    resolvable by paying, not a permissions error."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    error_type = "plan_required"


class TooManyRequestsError(NightGuardError):
    """Raised when a client exceeds a rate limit (e.g. login attempts)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_type = "too_many_requests"


class UnsupportedMediaTypeError(NightGuardError):
    """Raised when an uploaded file's type is not one of the ones this endpoint accepts."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    error_type = "unsupported_media_type"


class PayloadTooLargeError(NightGuardError):
    """Raised when an uploaded file exceeds the endpoint's size limit."""

    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    error_type = "payload_too_large"


class UnprocessableEntityError(NightGuardError):
    """Raised for a well-formed request that fails a business-logic check made after
    Pydantic validation (e.g. a file that parses but yields no extractable text)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_type = "unprocessable_entity"


async def night_guard_exception_handler(request: Request, exc: NightGuardError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": exc.error_type, "message": exc.message}},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Without this, Pydantic/FastAPI request-validation failures (bad body/query
    # shape, failed field_validator) fall through to FastAPI's own default
    # {"detail": [...]} body — the one error shape in the whole API that isn't
    # {"error": {"type", "message"}}, found via Phase 28's consistency audit.
    field_errors = [
        f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}" for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"type": "validation_error", "message": "; ".join(field_errors)}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Without this, an unexpected exception is completely invisible: FastAPI's own
    # handler is what would normally print a traceback, but registering a custom
    # Exception handler (needed for the consistent JSON error body) suppresses that
    # entirely. Found this gap the hard way — a real 500 during Phase 9 testing had
    # nothing to diagnose it with until this was added.
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"type": "internal_error", "message": "An unexpected error occurred."}},
    )


AI_UNAVAILABLE_MESSAGE = "The AI service is busy right now, so nothing was saved. Please try again in a minute."


async def llm_provider_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # The chat degrades gracefully on its own (orchestrator); this is for the screens that can't, such as saving a
    # knowledge document or asking the Training Room. A clear 503 instead of a crash, and nothing half-saved.
    logger.warning("AI provider unavailable on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": {"type": "ai_unavailable", "message": AI_UNAVAILABLE_MESSAGE}},
    )


def register_exception_handlers(app) -> None:
    from app.llm.base import LLMProviderError

    app.add_exception_handler(NightGuardError, night_guard_exception_handler)
    app.add_exception_handler(LLMProviderError, llm_provider_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
