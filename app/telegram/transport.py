import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from telethon import connection


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

    def options(self) -> dict:
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
            value = payload.get("proxies", []) if isinstance(payload, dict) else []
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
                    "type": route.type,
                    "host": _safe_host(route.host.get_secret_value()),
                    "port": route.port,
                    "managed_v2ray": route.managed_v2ray,
                    "name": route.v2ray_name or f"Route {index}",
                }
            )
        return result
