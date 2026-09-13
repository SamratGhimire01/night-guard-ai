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
    health,
    integrations,
    internal_metrics,
    knowledge,
    payments,
    premium_test,
    reports,
    services,
    staff,
    training,
    voice,
    webhooks,
    widget,
)
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.widget_cors import WidgetCORSMiddleware

configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name)

register_exception_handlers(app)
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
app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(appointments.router, prefix="/api/v1", tags=["appointments"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(followups.router, prefix="/api/v1", tags=["followups"])
app.include_router(handoffs.router, prefix="/api/v1", tags=["handoffs"])
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])
app.include_router(payments.router, prefix="/api/v1", tags=["payments"])
app.include_router(google_calendar.router, prefix="/api/v1", tags=["google-calendar"])
app.include_router(training.router, prefix="/api/v1", tags=["training"])
app.include_router(internal_metrics.router, prefix="/api/v1", tags=["internal"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(premium_test.router, prefix="/api/v1", tags=["premium-test"])
app.include_router(widget.router, tags=["widget"])
app.include_router(voice.router, tags=["voice"])
app.include_router(webhooks.router, tags=["webhooks"])
