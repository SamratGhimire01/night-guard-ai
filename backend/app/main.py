from fastapi import FastAPI

from app.api.routes import (
    appointments,
    auth,
    business,
    conversations,
    customers,
    followups,
    handoffs,
    health,
    internal_metrics,
    knowledge,
    reports,
    services,
    staff,
    training,
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
app.include_router(training.router, prefix="/api/v1", tags=["training"])
app.include_router(internal_metrics.router, prefix="/api/v1", tags=["internal"])
app.include_router(widget.router, tags=["widget"])
app.include_router(webhooks.router, tags=["webhooks"])
