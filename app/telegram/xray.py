"""Ephemeral local SOCKS bridge for dashboard-managed VLESS routes."""
from __future__ import annotations

import asyncio
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
    display_name: str = ""


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
    """Accept the VLESS + REALITY + TCP/RAW profile used by the dashboard."""
    try:
        parts = urlsplit(uri.strip())
        if parts.scheme.lower() != "vless" or not parts.username or not parts.hostname:
            raise VlessProfileError("PROFILE_INVALID")
        user_id = str(uuid.UUID(parts.username))
        port = parts.port
        if port is None or not 1 <= port <= 65535 or not _valid_host(parts.hostname):
            raise VlessProfileError("PROFILE_INVALID")
        query = parse_qs(parts.query, keep_blank_values=True)
        if _required(query, "encryption").lower() != "none":
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if _required(query, "security").lower() != "reality":
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if _required(query, "type").lower() not in {"tcp", "raw"}:
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        if _required(query, "headerType").lower() != "none":
            raise VlessProfileError("PROFILE_UNSUPPORTED")
        public_key = _required(query, "pbk")
        short_id = _required(query, "sid")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", public_key):
            raise VlessProfileError("PROFILE_INVALID")
        if not re.fullmatch(r"[0-9a-fA-F]{2,16}", short_id) or len(short_id) % 2:
            raise VlessProfileError("PROFILE_INVALID")
        return VlessRealityProfile(
            user_id=user_id,
            host=parts.hostname,
            port=port,
            sni=_required(query, "sni"),
            fingerprint=_required(query, "fp"),
            reality_public_key=public_key,
            short_id=short_id.lower(),
            display_name=unquote(parts.fragment),
        )
    except VlessProfileError:
        raise
    except (AttributeError, TypeError, ValueError):
        raise VlessProfileError("PROFILE_INVALID") from None


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _xray_config(profile: VlessRealityProfile, port: int) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{
                "address": profile.host,
                "port": profile.port,
                "users": [{"id": profile.user_id, "encryption": "none"}],
            }]},
            "streamSettings": {
                "method": "raw",
                "security": "reality",
                "rawSettings": {"header": {"type": "none"}},
                "realitySettings": {
                    "serverName": profile.sni,
                    "fingerprint": profile.fingerprint,
                    "password": profile.reality_public_key,
                    "shortId": profile.short_id,
                },
            },
        }],
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
