import platform

from telethon import TelegramClient

from app.config import Settings


def build_client(settings: Settings, options: dict | None = None, session=None) -> TelegramClient:
    if not settings.telegram_configured:
        raise ValueError("Telegram API credentials are not configured")
    session_path = settings.telegram_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client_options = {
        "device_model": "Desktop",
        "system_version": f"{platform.system()} {platform.release()}",
        "app_version": "1.45.0",
        "sequential_updates": False,
        "auto_reconnect": True,
        "connection_retries": 2,
        "request_retries": 2,
        "flood_sleep_threshold": 60,
    }
    client_options.update(options or {})
    return TelegramClient(
        session if session is not None else str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
        **client_options,
    )
