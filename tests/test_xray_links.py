import base64
import json

import pytest

from app.telegram.transport import TransportCatalog
from app.telegram.xray import VlessProfileError, _xray_config, parse_xray_uri


def test_common_xray_share_links_generate_distinct_outbounds(tmp_path):
    vmess = "vmess://" + base64.urlsafe_b64encode(json.dumps({
        "add": "edge.example.com", "port": "443", "id": "11111111-1111-4111-8111-111111111111",
        "aid": "0", "net": "ws", "tls": "tls", "path": "/v2", "host": "cdn.example.com", "ps": "My VMess",
    }).encode()).decode().rstrip("=")
    ss = "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:private-pass").decode().rstrip("=") + "@edge.example.com:8388#SS"
    links = [
        ("vless://11111111-1111-4111-8111-111111111111@edge.example.com:443?security=tls&type=ws&path=%2Fsocket&host=cdn.example.com&sni=cdn.example.com#TLS", "websocket", "vless"),
        (vmess, "websocket", "vmess"),
        ("trojan://private-pass@edge.example.com:443?security=tls&type=grpc&serviceName=telegram#Trojan", "grpc", "trojan"),
        (ss, "raw", "shadowsocks"),
    ]
    catalog = TransportCatalog(tmp_path / "proxies.json")
    for link, method, protocol in links:
        added = catalog.add_proxy_link(link)
        assert added["type"] in {"vless", "vmess", "trojan", "ss"}
        profile = parse_xray_uri(link)
        outbound = _xray_config(profile, 19200)["outbounds"][0]
        assert outbound["protocol"] == protocol
        assert outbound["streamSettings"]["method"] == method
        assert catalog.load()[added["index"] - 1].managed_v2ray


def test_telegram_mtproto_dd_and_standard_proxy_urls(tmp_path):
    catalog = TransportCatalog(tmp_path / "proxies.json")
    dd = "dd" + "11" * 16
    added = catalog.add_proxy_link(f"tg://proxy?server=proxy.example.com&port=443&secret={dd}")
    route = catalog.load()[added["index"] - 1]
    assert route.options()["proxy"][2] == dd
    for link, kind in [
        ("https://t.me/socks?server=proxy.example.com&port=1080&user=bob&pass=secret", "socks5"),
        ("socks5://bob:secret@proxy.example.com:1081", "socks5"),
        ("http://bob:secret@proxy.example.com:8080", "http"),
    ]:
        added = catalog.add_proxy_link(link)
        assert added["type"] == kind

    pasted = catalog.add_proxy_link("این پراکسی را امتحان کن: <https://t.me/socks?server=other.example.com&port=1080> ✅")
    assert pasted["type"] == "socks5"


def test_unknown_or_malformed_share_link_is_rejected_without_storage(tmp_path):
    catalog = TransportCatalog(tmp_path / "proxies.json")
    for link in ["vmess://not-base64", "ss://invalid", "hysteria2://secret@example.com:443"]:
        with pytest.raises(ValueError):
            catalog.add_proxy_link(link)
    assert catalog.load() == []


def test_unsupported_shadowsocks_plugin_is_not_silently_ignored():
    with pytest.raises(VlessProfileError, match="PROFILE_UNSUPPORTED"):
        parse_xray_uri("ss://aes-256-gcm:secret@example.com:8388?plugin=v2ray-plugin")
