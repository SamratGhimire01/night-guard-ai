"""Turns an unexpected exception into the API's normal JSON 500 *inside* the CORS middleware.

Starlette sends a handler registered for plain `Exception` to its outermost ServerErrorMiddleware, which sits outside
CORSMiddleware. The 500 it produced therefore had no Access-Control-Allow-Origin header, so the dashboard's browser
saw a bare network failure ("Failed to fetch") instead of the error message. Registered before CORSMiddleware in
main.py, which makes it the inner one."""

import logging

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class CatchUnhandledErrorsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            if started:  # part of the response is already out; nothing sensible left to send
                raise
            logger.exception("unhandled exception on %s %s", scope.get("method"), scope.get("path"))
            response = JSONResponse(
                status_code=500,
                content={"error": {"type": "internal_error", "message": "An unexpected error occurred."}},
            )
            await response(scope, receive, send)
