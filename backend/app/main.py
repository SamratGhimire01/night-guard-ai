from fastapi import FastAPI

from app.api.routes import auth, business, customers, health, services, staff
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name)

register_exception_handlers(app)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(customers.router, prefix="/api/v1", tags=["customers"])
app.include_router(business.router, prefix="/api/v1", tags=["business"])
app.include_router(services.router, prefix="/api/v1", tags=["services"])
app.include_router(staff.router, prefix="/api/v1", tags=["staff"])
