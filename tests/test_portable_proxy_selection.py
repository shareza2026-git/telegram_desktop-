import json
from types import SimpleNamespace

from app.telegram.transfer_bundle import TransferBundle
from app.telegram.transport import TransportCatalog


def test_portable_bundle_restores_last_working_proxy_on_new_machine(tmp_path):
    first_machine = TransportCatalog(tmp_path / "first" / "proxies.json")
    first_machine.set_selected_index(2)
    first_machine.export_records = lambda: [
        {"type": "socks5", "host": "proxy-one.example", "port": 1080},
        {"type": "socks5", "host": "proxy-two.example", "port": 1081},
    ]
    transfer_dir = tmp_path / "installed-folder"
    settings = SimpleNamespace(telegram_transfer_dir=transfer_dir, telegram_configured=False)

    TransferBundle(settings, first_machine).sync(include_session=False)

    portable = json.loads((transfer_dir / "telegram-proxies.json").read_text(encoding="utf-8"))
    assert portable["selected_index"] == 2
    second_machine_path = tmp_path / "second" / "proxies.json"
    second_machine_path.parent.mkdir()
    second_machine_path.write_text(json.dumps(portable), encoding="utf-8")
    second_machine = TransportCatalog(second_machine_path)
    assert second_machine.selected_index() == 2

    # A choice made on the second machine overrides the portable default.
    second_machine.set_selected_index(1)
    assert second_machine.selected_index() == 1
