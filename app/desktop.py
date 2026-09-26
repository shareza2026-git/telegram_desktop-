import argparse
import json
import os
import shutil
import sqlite3
import sys
import threading
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram Desktop local backend")
    parser.add_argument("--data-root", required=True, help="Writable private client data directory")
    parser.add_argument("--transfer-dir", help="Directory for portable transfer files")
    parser.add_argument("--port", type=int, default=8110, help="Loopback backend port for this instance")
    parser.add_argument("--parent-pid", type=int, help="Desktop parent process to monitor")
    parser.add_argument("--portable-config", help="Canonical writable portable Telegram bundle")
    parser.add_argument("--portable-mirror", help="Optional external mirror of the portable Telegram bundle")
    return parser.parse_args()


def _wait_for_windows_process_exit(pid: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize, False, int(pid))
    if not handle:
        return
    try:
        wait_for_single_object(handle, infinite)
    finally:
        close_handle(handle)


def _watch_parent(parent_pid: int, server) -> None:
    _wait_for_windows_process_exit(parent_pid)
    server.should_exit = True


def _session_has_auth_key(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(str(path))
        try:
            row = connection.execute(
                "SELECT length(auth_key) FROM sessions LIMIT 1"
            ).fetchone()
            return bool(row and row[0] and int(row[0]) >= 64)
        finally:
            connection.close()
    except Exception:
        return False


def _restore_portable_state(data_root: Path, transfer_dir: Path | None) -> None:
    if transfer_dir is None:
        return
    transfer_dir = transfer_dir.resolve()
    if not transfer_dir.is_dir():
        return

    data_root.mkdir(parents=True, exist_ok=True)
    account_dir = data_root / "accounts" / "default"
    account_dir.mkdir(parents=True, exist_ok=True)

    portable_session = transfer_dir / "telegram-session.session"
    local_session = account_dir / "client.session"
    if _session_has_auth_key(portable_session):
        temporary = account_dir / "client.session.portable.tmp"
        temporary.unlink(missing_ok=True)
        source = sqlite3.connect(str(portable_session))
        target = sqlite3.connect(str(temporary))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        if not _session_has_auth_key(temporary):
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Portable Telegram session is not usable")
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(local_session) + suffix).unlink(missing_ok=True)
        temporary.replace(local_session)

    portable_api = transfer_dir / "telegram-api.env"
    if portable_api.is_file():
        shutil.copy2(portable_api, data_root / "settings.env")

    portable_proxies = transfer_dir / "telegram-proxies.json"
    if portable_proxies.is_file():
        # Validate before replacing the private copy so a truncated portable
        # file cannot break startup.
        payload = json.loads(portable_proxies.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("proxies"), list):
            shutil.copy2(portable_proxies, data_root / "proxies.json")


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_root).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    transfer_dir = (
        Path(args.transfer_dir).expanduser().resolve()
        if args.transfer_dir
        else None
    )

    # The executable-folder portable bundle is authoritative. Restore it before
    # loading settings or creating Telethon's private session.
    _restore_portable_state(data_root, transfer_dir)

    # Load secrets from a user-owned file outside the installed application.
    # Existing process environment variables keep priority over file values.
    from dotenv import load_dotenv

    load_dotenv(data_root / "settings.env", override=False)

    # Packaged Windows installs must never bootstrap authorization from another
    # Telegram session. A fresh install always uses phone/code/2FA. Upgrades
    # keep using this app's own private session under the stable data root.
    os.environ["TELEGRAM_SOURCE_SESSION_PATH"] = ""
    os.environ["TELEGRAM_AUTO_IMPORT_SOURCE"] = "false"

    os.environ["TELEGRAM_CLIENT_DATA_ROOT"] = str(data_root)
    if transfer_dir is not None:
        os.environ["TELEGRAM_TRANSFER_DIR"] = str(transfer_dir)
    if args.portable_config:
        os.environ["TELEGRAM_PORTABLE_CONFIG"] = str(Path(args.portable_config).expanduser().resolve())
    if args.portable_mirror:
        os.environ["TELEGRAM_PORTABLE_MIRROR_CONFIG"] = str(Path(args.portable_mirror).expanduser().resolve())
    os.environ.setdefault(
        "TELEGRAM_SESSION_PATH",
        str(data_root / "accounts" / "default" / "client"),
    )
    os.environ.setdefault(
        "TELEGRAM_DATABASE_PATH",
        str(data_root / "accounts" / "default" / "client.db"),
    )
    os.environ.setdefault(
        "TELEGRAM_PROXY_CONFIG",
        str(data_root / "proxies.json"),
    )

    import uvicorn
    from app.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    if args.parent_pid:
        threading.Thread(
            target=_watch_parent,
            args=(args.parent_pid, server),
            name="desktop-parent-watchdog",
            daemon=True,
        ).start()
    server.run()


if __name__ == "__main__":
    main()
