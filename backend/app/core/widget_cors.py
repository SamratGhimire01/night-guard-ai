from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_WIDGET_STATIC_PATHS = ("/widget.js",)
_WIDGET_API_PREFIX = "/api/v1/widget/"


def _is_widget_path(path: str) -> bool:
    return path in _WIDGET_STATIC_PATHS or path.startswith(_WIDGET_API_PREFIX)


class WidgetCORSMiddleware(BaseHTTPMiddleware):
    """CORS, scoped ONLY to the public widget surface (GET /widget.js, POST
    /api/v1/widget/{business_id}/messages) — the widget snippet is meant to
    run embedded on ANY third-party website, so it genuinely needs
    cross-origin `fetch()` access from the browser.

    Deliberately NOT applied globally: every other endpoint in this codebase
    is bearer-token-authenticated business-dashboard API, never meant to be
    called from arbitrary browser JS on a third-party origin. Auth here is a
    JWT the caller's own JS must already possess and explicitly attach (not a
    cookie the browser sends automatically), so opening CORS wouldn't itself
    create a CSRF-style vulnerability on those routes — but scoping it
    narrowly to only the routes that actually need it is the smaller, more
    obviously-correct surface, so that's what's implemented.
    """

    async def dispatch(self, request: Request, call_next):
        if not _is_widget_path(request.url.path):
            return await call_next(request)

        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response
