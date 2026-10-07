# Project Contract

## Product

Telegram Desktop is an independent Windows Telegram-style desktop client.

Core stack:

- React + TypeScript + Vite frontend
- Tauri 2 desktop shell
- Python 3.12 + FastAPI backend
- Telethon Telegram client
- WebSocket live updates
- SQLite local persistence
- PyInstaller backend sidecar
- Tauri/NSIS Windows packaging

## Product scope

Supported/targeted desktop behavior includes:

- private chats, groups, channels, archive, unread state
- message history and paging
- send text/files
- reply, edit, delete, forward
- reactions
- typing indicators and read receipts
- pinned messages
- notifications
- drafts
- account/settings/profile
- Devices

Audio/video playback, calls, and Stories remain out of scope unless explicitly requested.

## Authoritative state

Telegram is authoritative for remote account/chat/message state.

The app's private SQLite store is local persistence/cache for this client and must not silently override fresher authoritative Telegram state.

Durable session/account state is authoritative over temporary frontend state.

UI state, spinners, timeouts, in-memory correlation, or optimistic rendering must not become durable truth.

## Session invariants

A new machine should create a new independent Telegram session unless the user explicitly requests an import/reuse workflow.

Session state must remain under the application's private data area, such as:

`data/telegram_desktop/accounts/default/client`

or the packaged application's private AppData root.

Do not expose phone numbers, OTP, 2FA passwords, authorization keys, API hash, session paths, or proxy secrets to the frontend/logs/Git.

`TELEGRAM_AUTO_IMPORT_SOURCE=false` is the safe default.

## Dashboard boundary

The trading dashboard is a separate repository and product.

Telegram Desktop may consume approved connection/proxy configuration only through read-only integration.

Never modify the dashboard's:

- files
- database
- session
- settings
- runtime state

## Connectivity

`TELEGRAM_ALLOW_DIRECT=false` is the required default.

No automatic direct fallback is allowed merely because proxy routes are unavailable. Direct connectivity requires an explicit user decision.

## Rendering invariant

Message text is trimmed for display so leading/trailing blank lines or spaces do not stretch message bubbles.

## Persistence and recovery

Retries must not duplicate committed side effects.

A failed operation must not be permanently recorded as successful.

After restart, the application must reconstruct valid state from authoritative durable sources rather than relying on transient UI/in-memory state.

## Non-goals

Do not redesign the project into the trading dashboard.

Do not share mutable runtime/session/database state with the dashboard.

Do not introduce release/runtime dependence on developer-only paths, shells, virtual environments, or IDE state.
