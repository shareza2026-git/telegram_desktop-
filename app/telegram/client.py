from telethon import TelegramClient

from app.config import Settings


def build_client(settings: Settings, options: dict | None = None) -> TelegramClient:
    if not settings.telegram_configured:
        raise ValueError("Telegram API credentials are not configured")
    session_path = settings.telegram_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
        sequential_updates=True,
        auto_reconnect=True,
        connection_retries=2,
        request_retries=2,
        flood_sleep_threshold=60,
        **(options or {}),
    )
