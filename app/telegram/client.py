import platform

from telethon import TelegramClient

from app.config import Settings


def build_client(settings: Settings, options: dict | None = None, session=None) -> TelegramClient:
    if not settings.telegram_configured:
        raise ValueError("Telegram API credentials are not configured")
    session_path = settings.telegram_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)
    # Shown in Telegram's "Devices" list. Match the official desktop client so
    # the session reads "Desktop" with a normal version instead of
    # "Unofficial Telegram Desktop".
    # Bold line of Telegram's "Devices" list. The app name below it
    # ("Unofficial Telegram Desktop") is tied to the API ID and stays.
    architecture = "x64" if platform.machine().endswith("64") else "x86"
    client_options = {
        "device_model": f"Desktop 7.3.3 {architecture}",
        "system_version": f"{platform.system()} {platform.release()}",
        "app_version": "1.45.0",
        "sequential_updates": False,
        "auto_reconnect": True,
        "connection_retries": 2,
        "request_retries": 2,
        "flood_sleep_threshold": 60,
        # Never catch up during connect: with a logged-out key and update state
        # left from an earlier login, Telethon treats the account as logged out
        # and disconnects itself, cancelling the login request. The service
        # catches up explicitly once authorization is confirmed.
        "catch_up": False,
    }
    client_options.update(options or {})
    return TelegramClient(
        session if session is not None else str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
        **client_options,
    )
