"""Request guard for the local desktop API.

The backend listens on 127.0.0.1, which every website open in a browser and
every local process can reach. Three checks keep it private to the desktop
shell:

1. Host must be the loopback address itself (blocks DNS rebinding).
2. A browser Origin, when present, must be one of the desktop origins
   (blocks cross-site form posts, which CORS does not stop).
3. When a session token is configured, every request must carry it, either as
   the X-Desktop-Token header or as a ``token`` query parameter (used by
   <img>/<video> sources and the WebSocket, which cannot set headers).
"""

import hmac
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send


DESKTOP_ORIGINS = frozenset(
    {
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    }
)

TOKEN_HEADER = "x-desktop-token"
OPEN_PATHS = frozenset({"/health"})


class DesktopGuard:
    def __init__(self, app: ASGIApp, *, token: str | None, port: int) -> None:
        self.app = app
        self.token = token or None
        self.hosts = {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            "127.0.0.1",
            "localhost",
            # Starlette's TestClient default host.
            "testserver",
        }

    def _allowed(self, scope: Scope) -> tuple[bool, int]:
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        host = headers.get("host", "").lower()
        if host not in self.hosts:
            return False, 403

        origin = headers.get("origin")
        if origin is not None and origin not in DESKTOP_ORIGINS:
            return False, 403

        if scope["path"] in OPEN_PATHS:
            return True, 200
        # CORS preflight never carries custom headers; CORSMiddleware answers it.
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            return True, 200
        if self.token is None:
            return True, 200

        supplied = headers.get(TOKEN_HEADER)
        if supplied is None:
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            supplied = (query.get("token") or [None])[0]
        if supplied and hmac.compare_digest(supplied.encode(), self.token.encode()):
            return True, 200
        return False, 401

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        allowed, code = self._allowed(scope)
        if allowed:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"detail":"Forbidden"}'})
