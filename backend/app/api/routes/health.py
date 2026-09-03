import logging

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import ServiceUnavailableError
from app.db.database import engine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check failed: database unreachable")
        raise ServiceUnavailableError("Database is unreachable.")

    return {"status": "ok", "database": "connected"}
