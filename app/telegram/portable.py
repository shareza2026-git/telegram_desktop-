from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote
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
    # Default packaged behavior is intentionally executable-folder-only.
    # Do not inspect cwd, Desktop, Downloads, or the shortcut location.
    values.append(Path(sys.executable).resolve().parent / PORTABLE_FILE_NAME)
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


def _mirror_path() -> Path | None:
    raw = str(os.environ.get("TELEGRAM_PORTABLE_MIRROR_CONFIG") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    mirror = _mirror_path()
    if mirror is not None and mirror != path:
        try:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_text(serialized, encoding="utf-8")
        except OSError:
            pass


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


def _session_authorization(path: Path) -> dict[str, Any]:
    candidates = [path, Path(str(path) + ".session")]
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        raise ValueError("Desktop session was not found")
    uri = f"file:{quote(source.resolve().as_posix(), safe='/:')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        row = connection.execute(
            "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[3]:
        raise ValueError("Desktop session is not authorized")
    return {
        "dc_id": int(row[0]),
        "server_address": str(row[1]),
        "port": int(row[2]),
        "auth_key_b64": base64.b64encode(bytes(row[3])).decode("ascii"),
    }


def _accounts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("accounts")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]

    legacy = payload.get("session")
    if isinstance(legacy, dict):
        account = {
            "id": payload.get("active_account_id") or "legacy",
            "display_name": payload.get("display_name") or "",
            "phone": payload.get("phone") or "",
            "session": dict(legacy),
        }
        return [account]
    return []


def _active_account(payload: dict[str, Any]) -> dict[str, Any] | None:
    accounts = _accounts(payload)
    if not accounts:
        return None
    active_id = str(payload.get("active_account_id") or "")
    if active_id:
        for account in accounts:
            if str(account.get("id")) == active_id:
                return account
    return accounts[0]


def sync_account_to_portable(
    settings: Settings,
    *,
    user_id: int,
    display_name: str | None,
    phone: str | None,
) -> Path | None:
    path = find_portable_config(settings)
    if path is None:
        return None

    payload = _load_payload(path)
    accounts = _accounts(payload)
    account_id = str(user_id)
    record = {
        "id": account_id,
        "display_name": display_name or "",
        "phone": phone or "",
        "session": _session_authorization(settings.telegram_session_path),
    }
    for index, existing in enumerate(accounts):
        if str(existing.get("id")) == account_id:
            accounts[index] = record
            break
    else:
        accounts.append(record)

    payload["version"] = 2
    payload["accounts"] = accounts
    payload["active_account_id"] = account_id
    payload.pop("session", None)
    payload.pop("display_name", None)
    payload.pop("phone", None)
    _write_payload(path, payload)
    return path


def remove_account_from_portable(settings: Settings, user_id: int | None) -> Path | None:
    path = find_portable_config(settings)
    if path is None or user_id is None:
        return path

    payload = _load_payload(path)
    account_id = str(user_id)
    accounts = [
        account for account in _accounts(payload)
        if str(account.get("id")) != account_id
    ]
    payload["version"] = 2
    payload["accounts"] = accounts
    payload["active_account_id"] = str(accounts[0].get("id")) if accounts else None
    payload.pop("session", None)
    payload.pop("display_name", None)
    payload.pop("phone", None)
    _write_payload(path, payload)
    return path


def _seed_session(settings: Settings, payload: dict[str, Any]) -> None:
    target = settings.telegram_session_path
    candidates = [target, Path(str(target) + ".session")]
    if any(path.is_file() for path in candidates):
        return

    account = _active_account(payload)
    session = account.get("session") if account else payload.get("session")
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
