from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.storage import ChatStore
from app.telegram.service import TelegramDesktopService
from app.telegram.relay import RelayService
from app.telegram.transport import TransportCatalog
from app.telegram.portable import apply_portable_config
from app.api.routes import router
from app.security import DESKTOP_ORIGINS, TOKEN_HEADER, DesktopGuard, ErrorEnvelope


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    apply_portable_config(active_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store = ChatStore(active_settings.database_path)
        await store.initialize()
        transport = TransportCatalog(active_settings.telegram_proxy_config)
        desktop = TelegramDesktopService(active_settings, store, transport)
        relay = RelayService(active_settings, desktop, transport)
        desktop.relay = relay
        application.state.chat_store = store
        application.state.telegram_desktop = desktop
        application.state.telegram_relay = relay
        try:
            await relay.start()
            await desktop.start()
            yield
        finally:
            await relay.close()
            await desktop.close()
            await store.close()

    application = FastAPI(title="Telegram Desktop", lifespan=lifespan)
    # Innermost: unexpected errors become JSON that still gets CORS headers.
    application.add_middleware(ErrorEnvelope)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(DESKTOP_ORIGINS),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", TOKEN_HEADER],
    )
    # Added last so it runs first, before CORS and routing.
    application.add_middleware(
        DesktopGuard,
        token=active_settings.desktop_token.get_secret_value() if active_settings.desktop_token else None,
        port=active_settings.backend_port,
    )
    application.include_router(router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "telegram-desktop"}

    return application


app = create_app()
