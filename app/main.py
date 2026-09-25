from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.storage import ChatStore
from app.telegram.service import TelegramDesktopService
from app.telegram.transport import TransportCatalog
from app.telegram.portable import apply_portable_config
from app.api.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    apply_portable_config(active_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store = ChatStore(active_settings.database_path)
        await store.initialize()
        transport = TransportCatalog(active_settings.telegram_proxy_config)
        desktop = TelegramDesktopService(active_settings, store, transport)
        application.state.chat_store = store
        application.state.telegram_desktop = desktop
        await desktop.start()
        try:
            yield
        finally:
            await desktop.close()
            await store.close()

    application = FastAPI(title="Telegram Desktop", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "telegram-desktop"}

    return application


app = create_app()
