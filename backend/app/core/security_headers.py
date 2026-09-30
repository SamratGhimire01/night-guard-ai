"""Standard protective headers on every API response (a route that sets its own, like the logo's CSP, keeps it)."""

_BASE = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), geolocation=(), payment=()"),
]
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app, *, hsts: bool = False):
        self.app = app
        self.headers = _BASE + ([_HSTS] if hsts else [])

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message):
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [h for h in self.headers if h[0] not in present]
            await send(message)

        await self.app(scope, receive, with_headers)
