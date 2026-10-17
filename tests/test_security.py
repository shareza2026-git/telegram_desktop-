from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.security import DesktopGuard


def build_app(token: str | None) -> FastAPI:
    application = FastAPI()

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    @application.post("/api/telegram/auth/logout")
    async def logout():
        return {"done": True}

    @application.websocket("/ws/telegram")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "READY"})
        await websocket.close()

    application.add_middleware(DesktopGuard, token=token, port=8110)
    return application


def test_health_stays_open_without_token():
    client = TestClient(build_app("secret"))
    assert client.get("/health").status_code == 200


def test_api_requires_token_header_or_query():
    client = TestClient(build_app("secret"))
    assert client.post("/api/telegram/auth/logout").status_code == 401
    assert client.post("/api/telegram/auth/logout", headers={"X-Desktop-Token": "wrong"}).status_code == 401
    assert client.post("/api/telegram/auth/logout", headers={"X-Desktop-Token": "secret"}).status_code == 200
    assert client.post("/api/telegram/auth/logout?token=secret").status_code == 200


def test_cross_site_form_post_is_rejected_even_with_token():
    client = TestClient(build_app("secret"))
    response = client.post(
        "/api/telegram/auth/logout?token=secret",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_dns_rebinding_host_is_rejected():
    client = TestClient(build_app(None))
    response = client.post(
        "/api/telegram/auth/logout",
        headers={"Host": "evil.example:8110"},
    )
    assert response.status_code == 403


def test_desktop_origin_is_allowed():
    client = TestClient(build_app("secret"))
    response = client.post(
        "/api/telegram/auth/logout",
        headers={"Origin": "http://tauri.localhost", "X-Desktop-Token": "secret"},
    )
    assert response.status_code == 200


def test_websocket_needs_token():
    client = TestClient(build_app("secret"))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/telegram") as socket:
            socket.receive_json()
    with client.websocket_connect("/ws/telegram?token=secret") as socket:
        assert socket.receive_json() == {"type": "READY"}
