# Architecture

## Process view

```text
React / TypeScript UI
        |
        | HTTP + WebSocket on loopback
        v
FastAPI backend (Python sidecar in packaged build)
        |
        +---- SQLite private local persistence
        |
        +---- read-only proxy/V2Ray catalog adapter
        |
        v
Telethon client
        |
        v
Telegram MTProto
```

The Tauri shell owns the desktop window lifecycle and packaged sidecar startup/shutdown.

## Frontend

Location: `frontend/`

Responsibilities:

- desktop conversation UI
- user actions and local presentation state
- HTTP calls to backend
- WebSocket live-event consumption
- local UI preferences/drafts where explicitly designed

The frontend must not receive API hash, Telegram authorization keys, proxy passwords, full V2Ray links, or filesystem session secrets.

## Desktop shell

Location: `frontend/src-tauri/`

Responsibilities:

- Windows desktop shell
- custom window lifecycle
- packaged backend sidecar lifecycle
- per-instance/runtime bootstrap
- NSIS packaging integration
- packaged external binaries such as Xray

## Backend

Location: `app/`

Responsibilities:

- FastAPI endpoints
- Telegram service orchestration
- safe configuration projection
- local store lifecycle
- login/session orchestration
- media/upload handling
- live event brokerage

Development backend port is normally `127.0.0.1:8110`.

## Telegram client

Location: `app/telegram/`

Telethon owns Telegram protocol interaction.

Remote Telegram state is authoritative when reconciling dialogs/messages/account/session status.

## Local persistence

SQLite is client-local state, not shared with the trading dashboard.

Development data should remain under `data/telegram_desktop/`.

Packaged builds must use a private writable per-user data root and must not write runtime state under Program Files.

## Dashboard integration

The dashboard is external to this repository.

Allowed integration is read-only configuration discovery/adaptation for approved proxy/V2Ray connection routes.

No dashboard database/session/settings writes are permitted.

## Network boundaries

- UI ↔ backend: loopback HTTP/WebSocket
- backend ↔ Telegram: Telethon/MTProto through configured route
- direct Telegram connection: disabled unless explicitly authorized
- dashboard integration: local read-only filesystem input only

## Startup / shutdown

Development:

- backend is started separately
- Tauri dev window connects to loopback backend

Packaged:

- Tauri starts the PyInstaller backend sidecar
- sidecar uses private per-user data root
- Tauri/parent process lifecycle is responsible for stopping the sidecar

## Release packaging

Git tag → GitHub Actions → tests → sidecar build → sidecar smoke test → Tauri/NSIS build → versioned installer → GitHub Release.

See `docs/RELEASE_PROCESS.md`.
