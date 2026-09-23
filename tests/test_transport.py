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
