"""Ephemeral local SOCKS bridge for dashboard-managed VLESS routes."""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import suppress
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
from urllib.parse import parse_qs, unquote, urlsplit
import uuid


READY_TIMEOUT_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 5.0


class VlessProfileError(ValueError):
    pass


class XrayRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VlessRealityProfile:
    user_id: str = field(repr=False)
    host: str
    port: int
    sni: str
    fingerprint: str
    reality_public_key: str = field(repr=False)
    short_id: str = field(repr=False)
    flow: str = ""
    display_name: str = ""
    security: str = "reality"
    network: str = "raw"
    path: str = ""
    host_header: str = ""
    service_name: str = ""
    alpn: tuple[str, ...] = ()
    outbound_protocol: str = "vless"
    password: str = field(default="", repr=False)
    method: str = ""
    alter_id: int = 0


def _required(query: dict[str, list[str]], name: str) -> str:
    value = (query.get(name) or [""])[0].strip()
    if not value:
        raise VlessProfileError("PROFILE_INVALID")
    return value


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.split(".")
        return bool(
            len(host) <= 253
            and re.fullmatch(r"[A-Za-z0-9.-]+", host)
            and all(label and len(label) <= 63 and not label.startswith("-") and not label.endswith("-") for label in labels)
        )


def parse_vless_uri(uri: str) -> VlessRealityProfile:
    """Parse common VLESS profiles without silently dropping transport settings."""
    try:
        parts = urlsplit(uri.strip())
        if parts.scheme.lower() != "vless" or not parts.username or not parts.hostname:
            raise VlessProfileError("PROFILE_INVALID")
        user_id = str(uuid.UUID(parts.username))
        port = parts.port
        if port is None or not 1 <= port <= 65535 or not _valid_host(parts.hostname):
            raise VlessProfileError("PROFILE_INVALID")
        query = parse_qs(parts.query, keep_blank_values=True)
        encryption = (query.get("encryption") or ["none"])[0].strip().lower()
        security = (query.get("security") or ["none"])[0].strip().lower()
        network = (query.get("type") or ["tcp"])[0].strip().lower()
        header_type = (
            (query.get("headerType") or query.get("headertype") or ["none"])[0]
            .strip()
            .lower()
        )
        flow = (query.get("flow") or [""])[0].strip()
        if encryption != "none":
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if security not in {"reality", "tls", "none"}:
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if network not in {"tcp", "raw", "ws", "websocket", "grpc", "xhttp", "httpupgrade"}:
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if header_type != "none" or (security == "reality" and network in {"ws", "websocket", "httpupgrade"}):
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if flow not in {"", "xtls-rprx-vision"} or (flow and network not in {"tcp", "raw"}):
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        public_key = _required(query, "pbk") if security == "reality" else ""
        short_id = (query.get("sid") or [""])[0].strip()
        if security == "reality" and not re.fullmatch(r"[A-Za-z0-9_-]{20,}", public_key):
            raise VlessProfileError("PROFILE_INVALID")
        if short_id and (
            not re.fullmatch(r"[0-9a-fA-F]{2,16}", short_id)
            or len(short_id) % 2
        ):
            raise VlessProfileError("PROFILE_INVALID")
        return VlessRealityProfile(
            user_id=user_id,
            host=parts.hostname,
            port=port,
            sni=(query.get("sni") or [parts.hostname])[0].strip(),
            fingerprint=(query.get("fp") or ["chrome"])[0].strip(),
            reality_public_key=public_key,
            short_id=short_id.lower(),
            flow=flow,
            display_name=unquote(parts.fragment),
            security=security,
            network={"tcp": "raw", "ws": "websocket"}.get(network, network),
            path=(query.get("path") or [""])[0],
            host_header=(query.get("host") or [""])[0],
            service_name=(query.get("serviceName") or query.get("servicename") or [""])[0],
            alpn=tuple(part.strip() for part in (query.get("alpn") or [""])[0].split(",") if part.strip()),
        )
    except VlessProfileError:
        raise
    except (AttributeError, TypeError, ValueError):
        raise VlessProfileError("PROFILE_INVALID") from None


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def parse_xray_uri(uri: str) -> VlessRealityProfile:
    """Convert a share link to a validated Xray outbound profile."""
    raw = uri.strip()
    scheme = raw.split(":", 1)[0].lower()
    if scheme == "vless":
        return parse_vless_uri(raw)
    try:
        if scheme == "vmess":
            payload = json.loads(_decode_base64(raw.split("://", 1)[1]).decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError
            host, port = str(payload["add"]), int(payload["port"])
            user_id = str(uuid.UUID(str(payload["id"])))
            network = str(payload.get("net") or "tcp").lower()
            security = str(payload.get("tls") or "none").lower()
            if security in {"", "false"}: security = "none"
            if network not in {"tcp", "raw", "ws", "websocket", "grpc"} or security not in {"none", "tls"}:
                raise VlessProfileError("PROFILE_UNSUPPORTED")
            profile = VlessRealityProfile(
                user_id=user_id, host=host, port=port,
                sni=str(payload.get("sni") or host), fingerprint=str(payload.get("fp") or "chrome"),
                reality_public_key="", short_id="", security=security,
                network={"tcp": "raw", "ws": "websocket"}.get(network, network),
                path=str(payload.get("path") or ""), host_header=str(payload.get("host") or ""),
                service_name=str(payload.get("path") or "") if network == "grpc" else "",
                outbound_protocol="vmess", alter_id=int(payload.get("aid") or 0),
                display_name=str(payload.get("ps") or ""),
            )
        elif scheme in {"trojan", "ss"}:
            if scheme == "ss":
                if "plugin=" in raw.lower():
                    raise VlessProfileError("PROFILE_UNSUPPORTED")
                authority = raw.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
                if "@" not in authority:
                    decoded = _decode_base64(authority).decode("utf-8")
                    raw = "ss://" + decoded + ("#" + raw.split("#", 1)[1] if "#" in raw else "")
                else:
                    encoded, server = authority.rsplit("@", 1)
                    if ":" not in encoded:
                        decoded = _decode_base64(encoded).decode("utf-8")
                        raw = raw.replace(authority, decoded + "@" + server, 1)
            parts = urlsplit(raw)
            host, port = parts.hostname, parts.port
            password = unquote(parts.username or "")
            method = ""
            if scheme == "ss":
                method, password = password, unquote(parts.password or "")
                if not method or not password:
                    raise ValueError
            if not host or not password or not port:
                raise ValueError
            query = parse_qs(parts.query)
            network = (query.get("type") or ["tcp"])[0].lower()
            security = (query.get("security") or ["tls" if scheme == "trojan" else "none"])[0].lower()
            if network not in {"tcp", "raw", "ws", "websocket", "grpc"} or security not in {"none", "tls", "reality"}:
                raise VlessProfileError("PROFILE_UNSUPPORTED")
            if security == "reality" and network in {"ws", "websocket"}:
                raise VlessProfileError("PROFILE_UNSUPPORTED")
            profile = VlessRealityProfile(
                user_id="", host=host, port=port, password=password, method=method,
                sni=(query.get("sni") or [host])[0], fingerprint=(query.get("fp") or ["chrome"])[0],
                reality_public_key=(query.get("pbk") or [""])[0], short_id=(query.get("sid") or [""])[0],
                security=security, network={"tcp": "raw", "ws": "websocket"}.get(network, network),
                path=(query.get("path") or [""])[0], host_header=(query.get("host") or [""])[0],
                service_name=(query.get("serviceName") or [""])[0],
                outbound_protocol="shadowsocks" if scheme == "ss" else "trojan",
                display_name=unquote(parts.fragment),
            )
        else:
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if not 1 <= profile.port <= 65535 or not _valid_host(profile.host):
            raise ValueError
        if profile.security == "reality" and not profile.reality_public_key:
            raise ValueError
        return profile
    except VlessProfileError:
        raise
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError, binascii.Error, OverflowError):
        raise VlessProfileError("PROFILE_INVALID") from None


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _xray_config(profile: VlessRealityProfile, port: int) -> dict:
    if profile.outbound_protocol == "shadowsocks":
        settings = {"servers": [{"address": profile.host, "port": profile.port, "method": profile.method, "password": profile.password}]}
    else:
        user = ({"id": profile.user_id, "encryption": "none", **({"flow": profile.flow} if profile.flow else {})}
                if profile.outbound_protocol == "vless" else
                {"id": profile.user_id, "alterId": profile.alter_id, "security": "auto"}
                if profile.outbound_protocol == "vmess" else {"password": profile.password})
        settings = {"vnext" if profile.outbound_protocol != "trojan" else "servers": [
            {"address": profile.host, "port": profile.port,
             **({"users": [user]} if profile.outbound_protocol != "trojan" else user)}
        ]}
    stream: dict = {"method": profile.network, "security": profile.security}
    if profile.network == "raw":
        stream["rawSettings"] = {"header": {"type": "none"}}
    elif profile.network == "websocket":
        stream["wsSettings"] = {"path": profile.path or "/", **({"host": profile.host_header} if profile.host_header else {})}
    elif profile.network == "grpc":
        stream["grpcSettings"] = {"serviceName": profile.service_name}
    elif profile.network == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": profile.path or "/", **({"host": profile.host_header} if profile.host_header else {})}
    elif profile.network == "xhttp":
        stream["xhttpSettings"] = {"path": profile.path or "/", **({"host": profile.host_header} if profile.host_header else {})}
    if profile.security == "reality":
        stream["realitySettings"] = {"serverName": profile.sni, "fingerprint": profile.fingerprint,
                                     "password": profile.reality_public_key, "shortId": profile.short_id}
    elif profile.security == "tls":
        stream["tlsSettings"] = {"serverName": profile.sni,
                                 **({"fingerprint": profile.fingerprint} if profile.fingerprint else {}),
                                 **({"alpn": list(profile.alpn)} if profile.alpn else {})}
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [{"protocol": profile.outbound_protocol, "settings": settings,
                       "streamSettings": stream}],
    }


class XrayRuntime:
    def __init__(self, profile: VlessRealityProfile, core_path: Path, runtime_directory: Path) -> None:
        self.profile = profile
        self.core_path = core_path
        self.runtime_directory = runtime_directory
        self.process: asyncio.subprocess.Process | None = None
        self.config_path: Path | None = None
        self.port = 0

    async def start(self) -> dict:
        if not self.core_path.is_file():
            raise XrayRuntimeError("XRAY_CORE_NOT_FOUND")
        self.port = _allocate_local_port()
        self.runtime_directory.mkdir(parents=True, exist_ok=True)
        self.config_path = self.runtime_directory / f"xray-vless-{secrets.token_hex(16)}.json"
        descriptor = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_xray_config(self.profile, self.port), handle, separators=(",", ":"))
        try:
            validation = await asyncio.to_thread(
                subprocess.run,
                [str(self.core_path), "run", "-test", "-c", str(self.config_path)],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if validation.returncode:
                raise XrayRuntimeError("XRAY_CONFIG_INVALID")
            self.process = await asyncio.create_subprocess_exec(
                str(self.core_path), "run", "-c", str(self.config_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + READY_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if self.process.returncode is not None:
                    raise XrayRuntimeError("XRAY_START_FAILED")
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", self.port)
                    writer.close()
                    await writer.wait_closed()
                    return {"proxy": {"proxy_type": "socks5", "addr": "127.0.0.1", "port": self.port, "rdns": True}}
                except OSError:
                    await asyncio.sleep(0.05)
            raise XrayRuntimeError("SOCKS_NOT_READY")
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, OSError):
                with suppress(ProcessLookupError):
                    process.kill()
                with suppress(asyncio.TimeoutError, OSError):
                    await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
        path, self.config_path = self.config_path, None
        if path is not None:
            with suppress(OSError):
                path.unlink()
