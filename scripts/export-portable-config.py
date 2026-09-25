from __future__ import annotations

import argparse
import base64
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from app.config import get_settings
from app.telegram.transport import TransportCatalog


def read_session(path: Path) -> dict:
    candidates = [path, Path(str(path) + ".session")]
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        raise SystemExit("Authorized desktop session was not found.")
    uri = f"file:{quote(source.resolve().as_posix(), safe='/:')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        row = connection.execute(
            "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[3]:
        raise SystemExit("Desktop session is not authorized.")
    return {
        "dc_id": int(row[0]),
        "server_address": str(row[1]),
        "port": int(row[2]),
        "auth_key_b64": base64.b64encode(bytes(row[3])).decode("ascii"),
    }


def route_record(route) -> tuple[str, dict]:
    if route.managed_v2ray:
        return "v2ray", {
            "id": route.route_id or "portable-v2ray",
            "name": route.display_name,
            "host": route.host.get_secret_value(),
            "port": route.port,
            "vless_uri": route.vless_uri.get_secret_value() if route.vless_uri else "",
        }
    return "proxy", {
        "type": route.type,
        "host": route.host.get_secret_value(),
        "port": route.port,
        "secret": route.secret.get_secret_value() if route.secret else None,
        "username": route.username.get_secret_value() if route.username else None,
        "password": route.password.get_secret_value() if route.password else None,
        "v2ray_name": route.v2ray_name,
        "route_id": route.route_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one portable Telegram Desktop configuration file.")
    parser.add_argument("--output", default="telegram-portable.json")
    parser.add_argument("--xray-core", default="xray.exe")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("Telegram API ID/HASH are not configured.")

    proxies: list[dict] = []
    v2ray: list[dict] = []
    for route in TransportCatalog(settings.telegram_proxy_config).load():
        kind, record = route_record(route)
        (v2ray if kind == "v2ray" else proxies).append(record)

    payload = {
        "version": 2,
        "api": {
            "id": settings.telegram_api_id,
            "hash": settings.telegram_api_hash.get_secret_value(),
        },
        "active_account_id": "current",
        "accounts": [
            {
                "id": "current",
                "display_name": "",
                "phone": "",
                "session": read_session(settings.telegram_session_path),
            }
        ],
        "allow_direct": settings.telegram_allow_direct,
        "xray_core": args.xray_core,
        "proxies": proxies,
        "v2ray": v2ray,
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Portable configuration written to: {output}")
    print("WARNING: This file contains credentials that can authorize the Telegram account. Keep it private.")


if __name__ == "__main__":
    main()
