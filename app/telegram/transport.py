import asyncio
import base64
import hashlib
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr
from telethon import connection

from app.telegram.dashboard_transport import dashboard_proxy_records
from app.telegram.xray import VlessProfileError, XrayRuntime, parse_xray_uri


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
                raw = bytes.fromhex(value) if len(value) % 2 == 0 and all(c in '0123456789abcdefABCDEF' for c in value) else base64.b64decode(
                    value + "=" * (-len(value) % 4),
                    altchars=b"-_",
                    validate=True,
                )
                if len(raw) not in {16, 17} or (len(raw) == 17 and raw[0] != 0xdd):
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
        profile = parse_xray_uri(self.vless_uri.get_secret_value())
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

    def _user_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".user.json")

    def _state_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".state.json")

    def _load_user_records(self) -> list[dict]:
        path = self._user_path()
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            return value.get("proxies", []) if isinstance(value, dict) else []
        except Exception:
            return []

    def _save_user_records(self, records: list[dict]) -> None:
        path = self._user_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"proxies": records}, ensure_ascii=False, indent=2), encoding="utf-8")

    def selected_index(self) -> int | None:
        path = self._state_path()
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            raw = value.get("selected_index")
            return int(raw) if raw is not None else None
        except Exception:
            return None

    def set_selected_index(self, index: int | None) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"selected_index": index}, indent=2), encoding="utf-8")

    def _xray_core_path(self) -> Path:
        bundled = Path(sys.executable).resolve().parent / "xray.exe"
        return bundled if bundled.is_file() else Path(shutil.which("xray") or bundled)

    def _xray_runtime_directory(self) -> Path:
        return self.path.parent / "runtime" / "xray"

    def add_proxy_link(self, link: str) -> dict:
        match = re.search(
            r"(?i)(?:tg://(?:proxy|socks)\?|https?://(?:t\.me|telegram\.me|telegram\.dog)/(?:proxy|socks)\?|"
            r"(?:vless|vmess|trojan|ss|socks5|socks4|http)://)[^\s<>]+",
            link,
        )
        raw = match.group(0).rstrip(".,،؛)>]") if match else link.strip()
        if not raw or len(raw) > 16384:
            raise ValueError("Proxy link is empty or too long")
        parsed = urlparse(raw)

        if parsed.scheme.casefold() in {"vless", "vmess", "trojan", "ss"}:
            try:
                profile = parse_xray_uri(raw)
            except VlessProfileError as error:
                if str(error) == "PROFILE_UNSUPPORTED":
                    raise ValueError("این پروتکل یا تنظیمات لینک با هستهٔ Xray فعلی پشتیبانی نمی‌شود.") from None
                raise ValueError("ساختار لینک V2Ray معتبر نیست.") from None
            fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
            record = {
                "type": "socks5",
                "host": "127.0.0.1",
                "port": 1080,
                "managed_v2ray": True,
                "v2ray_name": profile.display_name or f"{parsed.scheme.upper()} {profile.host}",
                "route_id": f"user-xray-{fingerprint}",
                "vless_uri": raw,
                "xray_core_path": str(self._xray_core_path()),
                "runtime_directory": str(self._xray_runtime_directory()),
            }
            records = self._load_user_records()
            for existing in records:
                if (
                    existing.get("managed_v2ray")
                    and str(existing.get("vless_uri") or "").strip() == raw
                ):
                    existing.update(record)
                    break
            else:
                records.append(record)
            self._save_user_records(records)

            routes = self.load()
            for index, route in enumerate(routes, 1):
                if (
                    route.managed_v2ray
                    and route.vless_uri is not None
                    and route.vless_uri.get_secret_value() == raw
                ):
                    return {
                        "index": index,
                        "name": route.display_name,
                        "type": parsed.scheme.casefold(),
                        "host": profile.host,
                        "port": profile.port,
                    }
            raise ValueError("V2Ray proxy could not be added")

        host = parsed.netloc.casefold()
        path = parsed.path.casefold()
        kind = None
        if parsed.scheme.casefold() == "tg" and parsed.netloc.casefold() in {"proxy", "socks"}:
            kind = parsed.netloc.casefold()
        elif parsed.scheme.casefold() in {"http", "https"} and host in {"t.me", "telegram.me", "telegram.dog"}:
            if path in {"/proxy", "/socks"}:
                kind = path.lstrip("/")
        if kind is None and parsed.scheme.casefold() in {"socks5", "socks4", "http"}:
            if not parsed.hostname or not parsed.port:
                raise ValueError("Proxy link is missing server or port")
            record = {
                "type": parsed.scheme.casefold(), "host": parsed.hostname, "port": parsed.port,
                "username": unquote(parsed.username) if parsed.username else None,
                "password": unquote(parsed.password) if parsed.password else None,
            }
            return self._store_proxy_record(record)
        if kind not in {"proxy", "socks"}:
            raise ValueError("Unsupported proxy link; use Telegram, SOCKS, HTTP, VLESS, VMess, Trojan or Shadowsocks")

        values = parse_qs(parsed.query)
        server = (values.get("server") or [""])[0].strip()
        port_raw = (values.get("port") or [""])[0].strip()
        if not server or not port_raw.isdigit():
            raise ValueError("Proxy link is missing server or port")
        port = int(port_raw)
        if port < 1 or port > 65535:
            raise ValueError("Proxy port is invalid")

        if kind == "proxy":
            secret = (values.get("secret") or [""])[0].strip()
            if not secret:
                raise ValueError("MTProto proxy link is missing secret")
            record = {"type": "mtproto", "host": server, "port": port, "secret": secret}
            # Telethon supports ordinary and dd MTProto secrets, but cannot
            # perform the Fake-TLS handshake required by ee secrets.
            if secret.lower().startswith("ee") and len(secret) > 34:
                raise ValueError("Fake-TLS MTProto (ee) is not supported by this Telegram client")
            ProxyRoute.model_validate(record).options()
        else:
            record = {
                "type": "socks5",
                "host": server,
                "port": port,
                "username": ((values.get("user") or [""])[0].strip() or None),
                "password": ((values.get("pass") or [""])[0].strip() or None),
            }

        return self._store_proxy_record(record)

    def _store_proxy_record(self, record: dict) -> dict:
        records = self._load_user_records()
        fingerprint = (record["type"], record["host"].casefold(), record["port"])
        for existing in records:
            current = (str(existing.get("type")), str(existing.get("host", "")).casefold(), int(existing.get("port", 0) or 0))
            if current == fingerprint:
                existing.update({key: value for key, value in record.items() if value is not None})
                break
        else:
            records.append(record)
        self._save_user_records(records)

        routes = self.load()
        for index in range(len(routes), 0, -1):
            route = routes[index - 1]
            if route.type == record["type"] and route.host.get_secret_value().casefold() == record["host"].casefold() and route.port == record["port"]:
                return {"index": index, "name": route.display_name, "type": route.type, "host": record["host"], "port": route.port}
        raise ValueError("Proxy could not be added")

    def load(self) -> list[ProxyRoute]:
        user_records = self._load_user_records()
        if not self.path.exists():
            if user_records:
                self.last_error = None
                return [ProxyRoute.model_validate(item) for item in user_records]
            self.last_error = "Proxy configuration was not found"
            return []

        base_records: list[dict] = []
        try:
            # PowerShell 5.x writes UTF-8 files with a BOM by default.
            # utf-8-sig accepts both BOM and normal UTF-8 JSON.
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError
            if "version" in payload and "routes" in payload and "direct" in payload:
                base_records = list(dashboard_proxy_records(self.path, payload))
            else:
                raw = payload.get("proxies", [])
                base_records = list(raw) if isinstance(raw, list) else []
            self.last_error = None
        except Exception:
            # A damaged seed file must never block proxies the user adds later.
            self.last_error = "Proxy configuration is invalid; using user proxies only"
            logging.getLogger(__name__).warning(self.last_error)

        records = base_records + user_records
        result: list[ProxyRoute] = []
        for item in records:
            try:
                normalized = dict(item)
                if normalized.get("managed_v2ray"):
                    normalized["xray_core_path"] = str(self._xray_core_path())
                    normalized["runtime_directory"] = str(self._xray_runtime_directory())
                result.append(ProxyRoute.model_validate(normalized))
            except Exception:
                logging.getLogger(__name__).warning("Skipping invalid proxy record")
        return result

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

    def export_records(self) -> list[dict]:
        records: list[dict] = []
        for route in self.load():
            item = {
                "type": route.type,
                "host": route.host.get_secret_value(),
                "port": route.port,
                "secret": route.secret.get_secret_value() if route.secret else None,
                "username": route.username.get_secret_value() if route.username else None,
                "password": route.password.get_secret_value() if route.password else None,
                "managed_v2ray": route.managed_v2ray,
                "v2ray_name": route.v2ray_name,
                "route_id": route.route_id,
                "vless_uri": route.vless_uri.get_secret_value() if route.vless_uri else None,
            }
            records.append({key: value for key, value in item.items() if value is not None})
        return records

    def snapshot(self) -> list[dict]:
        result = []
        for index, route in enumerate(self.load(), 1):
            result.append(
                {
                    "index": index,
                    "type": route.vless_uri.get_secret_value().split(":", 1)[0].lower() if route.managed_v2ray and route.vless_uri else route.type,
                    "host": _safe_host(route.host.get_secret_value()),
                    "port": route.port,
                    "managed_v2ray": route.managed_v2ray,
                    "name": route.display_name if route.display_name != "Proxy" else f"{route.host.get_secret_value()}:{route.port}",
                    "selected": self.selected_index() == index,
                }
            )
        return result
