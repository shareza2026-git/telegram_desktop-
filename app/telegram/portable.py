from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession

from app.config import Settings


PORTABLE_FILE_NAME = "telegram-portable.json"


def _candidate_paths(settings: Settings) -> list[Path]:
    values: list[Path] = []
    explicit = str(os.environ.get("TELEGRAM_PORTABLE_CONFIG") or "").strip()
    if explicit:
        values.append(Path(explicit))
    values.append(Path(sys.executable).resolve().parent / PORTABLE_FILE_NAME)
    values.append(Path.cwd() / PORTABLE_FILE_NAME)
    values.append(settings.project_root / PORTABLE_FILE_NAME)
    unique: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        resolved = value.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def find_portable_config(settings: Settings) -> Path | None:
    for path in _candidate_paths(settings):
        if path.is_file():
            return path
    return None


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Portable Telegram configuration is invalid") from None
    if not isinstance(payload, dict):
        raise ValueError("Portable Telegram configuration is invalid")
    return payload


def _write_proxy_catalog(settings: Settings, payload: dict[str, Any]) -> None:
    proxies = payload.get("proxies") or []
    v2ray = payload.get("v2ray") or []
    if not isinstance(proxies, list) or not isinstance(v2ray, list):
        raise ValueError("Portable proxy configuration is invalid")

    xray_core = payload.get("xray_core")
    default_core = Path(sys.executable).resolve().parent / "xray.exe"
    core_path = Path(str(xray_core)).expanduser() if xray_core else default_core
    if not core_path.is_absolute():
        core_path = (Path(sys.executable).resolve().parent / core_path).resolve()

    runtime = settings.data_root / "runtime" / "xray"
    records: list[dict[str, Any]] = []
    for row in proxies:
        if isinstance(row, dict):
            records.append(dict(row))
    for row in v2ray:
        if not isinstance(row, dict):
            continue
        uri = str(row.get("vless_uri") or "").strip()
        if not uri:
            continue
        records.append({
            "type": "socks5",
            "host": str(row.get("host") or "127.0.0.1"),
            "port": int(row.get("port") or 1080),
            "managed_v2ray": True,
            "v2ray_name": str(row.get("name") or "V2Ray"),
            "route_id": str(row.get("id") or "portable-v2ray"),
            "vless_uri": uri,
            "xray_core_path": str(core_path),
            "runtime_directory": str(runtime),
        })

    target = settings.data_root / "portable" / "proxies.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"proxies": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.telegram_proxy_config = target


def _seed_session(settings: Settings, payload: dict[str, Any]) -> None:
    target = settings.telegram_session_path
    candidates = [target, Path(str(target) + ".session")]
    if any(path.is_file() for path in candidates):
        return

    session = payload.get("session")
    if not isinstance(session, dict):
        return
    try:
        dc_id = int(session["dc_id"])
        server_address = str(session["server_address"])
        port = int(session["port"])
        auth_key = base64.b64decode(str(session["auth_key_b64"]), validate=True)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Portable session authorization is invalid") from None
    if not auth_key:
        raise ValueError("Portable session authorization is invalid")

    target.parent.mkdir(parents=True, exist_ok=True)
    sqlite_session = SQLiteSession(str(target))
    try:
        sqlite_session.set_dc(dc_id, server_address, port)
        sqlite_session.auth_key = AuthKey(data=auth_key)
        sqlite_session.save()
    finally:
        sqlite_session.close()


def apply_portable_config(settings: Settings) -> Path | None:
    path = find_portable_config(settings)
    if path is None:
        return None

    payload = _load_payload(path)
    api = payload.get("api")
    if not isinstance(api, dict):
        raise ValueError("Portable API configuration is missing")
    try:
        api_id = int(api["id"])
        api_hash = str(api["hash"]).strip()
    except (KeyError, TypeError, ValueError):
        raise ValueError("Portable API configuration is invalid") from None
    if api_id <= 0 or not api_hash:
        raise ValueError("Portable API configuration is invalid")

    settings.telegram_api_id = api_id
    settings.telegram_api_hash = SecretStr(api_hash)
    settings.telegram_allow_direct = bool(payload.get("allow_direct", settings.telegram_allow_direct))
    _write_proxy_catalog(settings, payload)
    _seed_session(settings, payload)
    return path
