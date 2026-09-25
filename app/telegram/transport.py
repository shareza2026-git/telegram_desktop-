import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr
from telethon import connection

from app.telegram.dashboard_transport import dashboard_proxy_records
from app.telegram.xray import XrayRuntime, parse_vless_uri


class ProxyRoute(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    type: Literal["mtproto", "socks5", "socks4", "http"]
    host: SecretStr
    port: int = Field(ge=1, le=65535)
    secret: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    managed_v2ray: bool = False
    v2ray_name: str | None = None
    route_id: str | None = None
    vless_uri: SecretStr | None = None
    xray_core_path: Path | None = None
    runtime_directory: Path | None = None
    _runtime: XrayRuntime | None = PrivateAttr(default=None)

    @property
    def display_name(self) -> str:
        return self.v2ray_name or self.route_id or "Proxy"

    def options(self) -> dict:
        if self.managed_v2ray:
            raise RuntimeError("Managed V2Ray route must be activated first")
        if self.type == "mtproto":
            value = self.secret.get_secret_value() if self.secret else ""
            try:
                raw = bytes.fromhex(value) if len(value) == 32 else base64.b64decode(
                    value + "=" * (-len(value) % 4),
                    altchars=b"-_",
                    validate=True,
                )
                if len(raw) != 16:
                    raise ValueError
            except Exception:
                raise ValueError("Invalid MTProto secret") from None
            return {
                "connection": connection.ConnectionTcpMTProxyRandomizedIntermediate,
                "proxy": (self.host.get_secret_value(), self.port, raw.hex()),
            }

        proxy = {
            "proxy_type": self.type,
            "addr": self.host.get_secret_value(),
            "port": self.port,
            "rdns": True,
        }
        for field in ("username", "password"):
            value = getattr(self, field)
            if value:
                proxy[field] = value.get_secret_value()
        return {"proxy": proxy}

    async def activate(self) -> dict:
        if not self.managed_v2ray:
            return self.options()
        if self.vless_uri is None or self.xray_core_path is None or self.runtime_directory is None:
            raise RuntimeError("Managed V2Ray route is incomplete")
        profile = parse_vless_uri(self.vless_uri.get_secret_value())
        self._runtime = XrayRuntime(profile, self.xray_core_path, self.runtime_directory)
        return await self._runtime.start()

    async def deactivate(self) -> None:
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            await runtime.stop()


def _safe_host(value: str) -> str:
    if ":" in value and value.count(":") == 1:
        host, port = value.split(":")
        return f"{host[:4]}***:{port}"
    pieces = value.split(".")
    if len(pieces) == 4:
        pieces[-1] = "***"
        return ".".join(pieces)
    return value[:4] + "***" if len(value) > 4 else "***"


class TransportCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_error: str | None = None

    def load(self) -> list[ProxyRoute]:
        if not self.path.exists():
            self.last_error = "Proxy configuration was not found"
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            if "version" in payload and "routes" in payload and "direct" in payload:
                value = dashboard_proxy_records(self.path, payload)
            else:
                value = payload.get("proxies", [])
            self.last_error = None
            return [ProxyRoute.model_validate(item) for item in value]
        except Exception:
            self.last_error = "Proxy configuration is invalid"
            logging.getLogger(__name__).warning(self.last_error)
            return []

    async def probe(self, route: ProxyRoute, timeout: float = 4.0) -> float:
        started = asyncio.get_running_loop().time()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(route.host.get_secret_value(), route.port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
        except Exception:
            raise ConnectionError("Proxy route is unavailable") from None
        return round((asyncio.get_running_loop().time() - started) * 1000, 2)

    def snapshot(self) -> list[dict]:
        result = []
        for index, route in enumerate(self.load(), 1):
            result.append(
                {
                    "index": index,
                    "type": "vless" if route.managed_v2ray else route.type,
                    "host": _safe_host(route.host.get_secret_value()),
                    "port": route.port,
                    "managed_v2ray": route.managed_v2ray,
                    "name": route.display_name if route.display_name != "Proxy" else f"Route {index}",
                }
            )
        return result
