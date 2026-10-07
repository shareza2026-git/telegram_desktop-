import json
import sys
from pathlib import Path

from app.telegram.transport import TransportCatalog
from app.telegram.xray import _xray_config, parse_vless_uri


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


def test_add_proxy_link_accepts_vless_reality_and_rebinds_xray_paths(tmp_path):
    path = tmp_path / "proxies.json"
    path.write_text('{"proxies":[]}', encoding="utf-8")
    catalog = TransportCatalog(path)
    link = (
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?encryption=none&security=reality&type=tcp&sni=example.com"
        "&fp=chrome&pbk=abcdefghijklmnopqrstuvwx1234567890ABCD"
        "&sid=aabb&flow=xtls-rprx-vision#Portable"
    )

    added = catalog.add_proxy_link(link)
    routes = catalog.load()
    route = routes[added["index"] - 1]

    assert added["type"] == "vless"
    assert route.managed_v2ray is True
    assert route.vless_uri.get_secret_value() == link
    assert route.v2ray_name == "Portable"
    assert route.xray_core_path == Path(sys.executable).resolve().parent / "xray.exe"
    assert route.runtime_directory == path.parent / "runtime" / "xray"


def test_vless_reality_tcp_accepts_blank_header_type():
    link = (
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?security=reality&type=tcp&headerType=&path=&host="
        "&sni=example.com&fp=edge"
        "&pbk=abcdefghijklmnopqrstuvwx1234567890ABCD"
        "&sid=aabb#BlankHeader"
    )

    profile = parse_vless_uri(link)

    assert profile.host == "example.com"
    assert profile.port == 443
    assert profile.sni == "example.com"
    assert profile.fingerprint == "edge"
    assert profile.display_name == "BlankHeader"


def test_vless_reality_xhttp_is_parsed_and_rendered_for_xray():
    link = (
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?security=reality&type=xhttp&headerType=&path=/path&host=cdn.example.com"
        "&mode=auto&extra=%7B%22scMaxEachPostBytes%22%3A1000000%2C%22xPaddingBytes%22%3A%22100-1000%22%2C%22noGRPCHeader%22%3Afalse%7D"
        "&sni=example.com&fp=edge"
        "&pbk=abcdefghijklmnopqrstuvwx1234567890ABCD"
        "&sid=aabb#XHTTP"
    )

    profile = parse_vless_uri(link)
    config = _xray_config(profile, 19080)
    stream = config["outbounds"][0]["streamSettings"]

    assert profile.transport == "xhttp"
    assert profile.xhttp_path == "/path"
    assert profile.xhttp_host == "cdn.example.com"
    assert profile.xhttp_mode == "auto"
    assert stream["method"] == "xhttp"
    assert stream["xhttpSettings"]["path"] == "/path"
    assert stream["xhttpSettings"]["host"] == "cdn.example.com"
    assert stream["xhttpSettings"]["extra"]["scMaxEachPostBytes"] == 1000000
    assert stream["xhttpSettings"]["extra"]["noGRPCHeader"] is False
    assert "rawSettings" not in stream


def test_add_proxy_bundle_accepts_multiple_markdown_wrapped_vless_links(tmp_path):
    path = tmp_path / "proxies.json"
    path.write_text('{"proxies":[]}', encoding="utf-8")
    catalog = TransportCatalog(path)
    first = (
        "vless://11111111-1111-4111-8111-111111111111@one.example.com:443"
        "?security=reality&type=tcp&headerType=&sni=one.example.com&fp=edge"
        "&pbk=abcdefghijklmnopqrstuvwx1234567890ABCD&sid=aabb#One"
    )
    second = (
        "vless://22222222-2222-4222-8222-222222222222@two.example.com:443"
        "?security=reality&type=xhttp&path=/path&host=cdn.example.com&mode=auto"
        "&sni=two.example.com&fp=edge&pbk=abcdefghijklmnopqrstuvwx1234567890ABCD&sid=aabb#Two"
    )

    result = catalog.add_proxy_bundle(f"`{first}`\\\n\n`{second}`")

    assert len(result["added"]) == 2
    assert result["failed"] == 0
    routes = catalog.load()
    assert [route.v2ray_name for route in routes] == ["One", "Two"]
    assert all(route.managed_v2ray for route in routes)
