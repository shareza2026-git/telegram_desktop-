import json

from app.telegram.transport import TransportCatalog


def test_transport_snapshot_redacts_host_and_never_returns_secrets(tmp_path):
    path = tmp_path / "proxies.json"
    path.write_text(
        json.dumps(
            {
                "allow_direct": False,
                "proxies": [
                    {
                        "type": "socks5",
                        "host": "123.45.67.89",
                        "port": 1080,
                        "username": "private-user",
                        "password": "private-password",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    snapshot = TransportCatalog(path).snapshot()
    assert snapshot[0]["host"] == "123.45.67.***"
    assert "private-password" not in str(snapshot)


def test_dashboard_catalog_loads_legacy_proxy_and_managed_v2ray_read_only(tmp_path):
    dashboard = tmp_path / "DASHBOARD"
    config_path = dashboard / "data" / "config" / "connection_routes.json"
    config_path.parent.mkdir(parents=True)
    (dashboard / "config").mkdir()
    (dashboard / "config" / "telegram_proxies.yaml").write_text(
        """proxies:\n  - id: native\n    enabled: true\n    type: mtproto\n    host: proxy.example.com\n    port: 443\n    secret: 00112233445566778899aabbccddeeff\n    priority: 2\n""",
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps({
            "version": 1,
            "direct": {"enabled": True},
            "preferred": {},
            "routes": [{
                "id": "managed",
                "name": "Dashboard V2Ray",
                "kind": "MANAGED_XRAY",
                "enabled": True,
                "priority": 1,
                "vless_uri": "vless://11111111-1111-4111-8111-111111111111@example.com:443?encryption=none&security=reality&type=tcp&headerType=none&sni=example.com&fp=chrome&pbk=abcdefghijklmnopqrstuv&sid=aabb#Managed",
            }],
        }),
        encoding="utf-8",
    )

    catalog = TransportCatalog(config_path)
    routes = catalog.load()
    snapshot = catalog.snapshot()

    assert [route.display_name for route in routes] == ["Dashboard V2Ray", "native"]
    assert snapshot[0]["managed_v2ray"] is True
    assert snapshot[0]["type"] == "vless"
    assert snapshot[1]["type"] == "mtproto"
    assert "00112233445566778899aabbccddeeff" not in str(snapshot)
