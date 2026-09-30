import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    appointments,
    auth,
    business,
    conversations,
    customers,
    followups,
    google_calendar,
    handoffs,
    inbox,
    health,
    integrations,
    internal_metrics,
    knowledge,
    payments,
    qr_view,
    reports,
    services,
    staff,
    team,
    training,
    voice,
    webhooks,
    widget,
)
from app.core.config import settings
from app.core.error_middleware import CatchUnhandledErrorsMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.production_checks import enforce as enforce_production_config
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.widget_cors import WidgetCORSMiddleware
from app.services import scheduler

configure_logging(settings.log_level)
# ENVIRONMENT=production: refuse to start with an unsafe configuration, warn about risky choices (see the module).
enforce_production_config(settings)
_production = settings.environment == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Phase 45 — the first real "runs on its own clock" background task in
    this codebase (Phase 30 found no lifespan hook existed at all). Started
    here rather than at import time so it only ever runs against a real,
    live uvicorn process — FastAPI's TestClient does NOT invoke lifespan
    events unless used as a `with TestClient(app) as client:` context
    manager, which no test in this codebase does (confirmed directly before
    writing this), so the entire automated test suite is completely
    unaffected by this loop ever existing. Cancelled and awaited on shutdown
    so a real SIGTERM doesn't leave the task dangling — the same "wait for
    real in-flight work to finish" discipline Phase 30 found uvicorn's
    default shutdown already provides for HTTP requests."""
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# The interactive API docs describe every route; useful in development, not something to publish in production.
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if _production else "/docs",
    redoc_url=None if _production else "/redoc",
    openapi_url=None if _production else "/openapi.json",
)

register_exception_handlers(app)
# Innermost of the three: an unexpected error becomes a JSON 500 that still gets CORS headers (see the module).
app.add_middleware(CatchUnhandledErrorsMiddleware)
app.add_middleware(SecurityHeadersMiddleware, hsts=_production)
# Order matters: Starlette makes the LAST-added middleware the OUTERMOST one, so it
# sees a request first. WidgetCORSMiddleware must be outermost — it fully owns CORS
# for widget paths (including handling their OPTIONS preflight itself with a
# wildcard origin) and passes every other path straight through via call_next.
# Added the other way around once (Phase 35), which broke the real widget: the
# dashboard's CORSMiddleware ran first, saw the widget's arbitrary third-party
# origin wasn't in its own narrow allowlist, and rejected the preflight with a
# raw 400 before WidgetCORSMiddleware ever got a chance to handle it (caught by
# tests/integration/test_widget.py::test_cors_headers_present_on_widget_endpoints_but_not_elsewhere).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.dashboard_cors_origins.split(",") if o.strip()],
    # Dev convenience: any ngrok free-tier tunnel origin, not just one hardcoded URL pinned in
    # DASHBOARD_CORS_ORIGINS -- that URL rotates every time a local dev tunnel restarts (a real
    # incident: it broke a real login with a bare "Login failed", no CORS error surfaced to the
    # user). Safe here specifically because auth is a bearer token in sessionStorage, never a
    # cookie -- a stranger's own ngrok tunnel being allowed to ask this API a question can't read
    # or steal anything of this app's, since it never has this app's token in the first place.
    allow_origin_regex=None if _production else r"^https://[a-zA-Z0-9-]+\.ngrok-free\.(app|dev)$",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(WidgetCORSMiddleware)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(customers.router, prefix="/api/v1", tags=["customers"])
app.include_router(business.router, prefix="/api/v1", tags=["business"])
app.include_router(services.router, prefix="/api/v1", tags=["services"])
app.include_router(staff.router, prefix="/api/v1", tags=["staff"])
app.include_router(team.router, prefix="/api/v1", tags=["team"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(appointments.router, prefix="/api/v1", tags=["appointments"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(followups.router, prefix="/api/v1", tags=["followups"])
app.include_router(handoffs.router, prefix="/api/v1", tags=["handoffs"])
app.include_router(inbox.router, prefix="/api/v1", tags=["inbox"])
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])
app.include_router(payments.router, prefix="/api/v1", tags=["payments"])
app.include_router(google_calendar.router, prefix="/api/v1", tags=["google-calendar"])
app.include_router(training.router, prefix="/api/v1", tags=["training"])
app.include_router(internal_metrics.router, prefix="/api/v1", tags=["internal"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(widget.router, tags=["widget"])
app.include_router(qr_view.router, tags=["qr"])
app.include_router(voice.router, tags=["voice"])
app.include_router(webhooks.router, tags=["webhooks"])
