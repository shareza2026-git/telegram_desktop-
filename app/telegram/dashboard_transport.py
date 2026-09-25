"""Read the trading dashboard's connection catalog without modifying it."""
from __future__ import annotations

from pathlib import Path
import shutil

from dotenv import dotenv_values
import yaml

from app.telegram.xray import parse_vless_uri


VALID_PROXY_TYPES = {"mtproto", "socks5", "socks4", "http"}


def _secret(row: dict, name: str, environment: dict[str, str]) -> str | None:
    direct = str(row.get(name) or "").strip()
    if direct:
        return direct
    env_name = str(row.get(f"{name}_env") or "").strip()
    return str(environment.get(env_name) or "").strip() or None


def dashboard_proxy_records(config_path: Path, payload: dict) -> list[dict]:
    dashboard_root = config_path.resolve().parents[2]
    environment = {
        key: value or "" for key, value in dotenv_values(dashboard_root / ".env").items()
    }
    prioritized: list[tuple[int, dict]] = []

    legacy_path = dashboard_root / "config" / "telegram_proxies.yaml"
    if legacy_path.is_file():
        legacy = yaml.safe_load(legacy_path.read_text(encoding="utf-8")) or {}
        for row in legacy.get("proxies", []):
            if not isinstance(row, dict) or not row.get("enabled", True):
                continue
            proxy_type = str(row.get("type") or "").casefold()
            if proxy_type not in VALID_PROXY_TYPES:
                continue
            route_name = str(row.get("id") or "Telegram proxy")
            prioritized.append((int(row.get("priority", 100)), {
                "type": proxy_type,
                "host": str(row.get("host") or ""),
                "port": int(row.get("port")),
                "secret": _secret(row, "secret", environment),
                "username": _secret(row, "username", environment),
                "password": _secret(row, "password", environment),
                "v2ray_name": route_name,
                "route_id": f"telegram-proxy:{route_name}",
            }))

    core_path = dashboard_root / "data" / "tools" / "xray" / "xray.exe"
    discovered = shutil.which("xray")
    if not core_path.is_file() and discovered:
        core_path = Path(discovered)
    runtime_directory = Path(__file__).resolve().parents[2] / "data" / "telegram_desktop" / "runtime" / "xray"

    for row in payload.get("routes", []):
        if not isinstance(row, dict) or not row.get("enabled", True):
            continue
        kind = str(row.get("kind") or "").upper()
        route_id = str(row.get("id") or "route")
        route_name = str(row.get("name") or route_id)
        priority = int(row.get("priority", 100))
        if kind == "TELEGRAM_PROXY":
            proxy = dict(row.get("proxy") or {})
            proxy_type = str(proxy.get("proxy_type") or proxy.get("type") or "").casefold()
            if proxy_type not in VALID_PROXY_TYPES:
                continue
            prioritized.append((priority, {
                "type": proxy_type,
                "host": str(proxy.get("host") or proxy.get("addr") or ""),
                "port": int(proxy.get("port")),
                "secret": str(proxy.get("secret") or "") or None,
                "username": str(proxy.get("username") or "") or None,
                "password": str(proxy.get("password") or "") or None,
                "v2ray_name": route_name,
                "route_id": route_id,
            }))
        elif kind == "MANAGED_XRAY":
            uri = str(row.get("vless_uri") or "").strip()
            try:
                profile = parse_vless_uri(uri)
            except ValueError:
                continue
            prioritized.append((priority, {
                "type": "socks5",
                "host": profile.host,
                "port": profile.port,
                "managed_v2ray": True,
                "v2ray_name": route_name,
                "route_id": route_id,
                "vless_uri": uri,
                "xray_core_path": core_path,
                "runtime_directory": runtime_directory,
            }))

    prioritized.sort(key=lambda item: item[0])
    return [record for _, record in prioritized]
