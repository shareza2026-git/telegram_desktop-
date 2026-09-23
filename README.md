# Telegram Desktop

A standalone Windows Telegram-style desktop client built independently from the trading terminal.

## Goals

- Reuse the trading terminal's Telegram API configuration and proxy/V2Ray routes through a read-only local adapter.
- Keep an independent Telegram session and local chat/message database.
- Present accessible private chats, groups, channels, archived chats and folders in a Telegram Desktop-like interface.
- Load message history lazily and receive live updates.
- Show image/file messages; video and audio playback are intentionally deferred.
- Never commit `.env`, Telegram sessions, proxy secrets or V2Ray links.

The trading terminal remains a separate repository and its running session file is never opened for write by this project.

## Implemented foundation

1. Safe configuration and transport discovery.
2. Independent local session/database paths.
3. Dialog list, message history, send-text and live update API.
4. Telegram Desktop-style three-column UI shell.
5. Read-only media metadata; no video/audio playback.

## Phase 2: controlled session bootstrap

When `TELEGRAM_SOURCE_SESSION_PATH` points to an existing Telethon `.session` file:

1. The backend reports `IMPORT_READY` instead of opening the source.
2. The user explicitly starts import from the UI or `POST /api/telegram/session/import`.
3. The source SQLite file is queried in read-only mode.
4. Only the authorization data needed to seed a new local session file is written under `data/telegram_desktop`.
5. The new session is connected through the read-only transport catalog.

`TELEGRAM_AUTO_IMPORT_SOURCE` is disabled by default. The app will not import a source session silently.

Important: this bootstrap creates a separate local session file, but it reuses the Telegram authorization key from the source. It is not a new Telegram device authorization. For a separate Telegram authorization, use the normal phone/code/2FA login flow instead.

## Phase 3: local phone/code/2FA login

If no source import is selected, the UI supports sending a Telegram login code, verifying the code, requesting the 2FA password when needed, and refreshing dialogs after authorization. Authentication errors are returned without logging phone numbers, codes, passwords or session values.

## Phase 4: dialogs, folders, unread and history paging

The client now supports:

1. Refreshing the live dialog list from Telegram.
2. Functional views for all chats, private chats, groups, channels and archived chats.
3. Showing unread counts from Telegram and marking a chat read when it is opened.
4. Loading older messages page by page with the existing independent local message store.

## Local configuration

Copy `.env.example` to `.env` locally and fill in values without committing the file.

- `TELEGRAM_SESSION_PATH`: independent client session path.
- `TELEGRAM_SOURCE_SESSION_PATH`: optional source session path from the dashboard; read-only.
- `TELEGRAM_PROXY_CONFIG`: read-only proxy/route catalog, including existing local V2Ray routes.
- `TELEGRAM_ALLOW_DIRECT`: remains false unless direct fallback is deliberately enabled.

The frontend never receives `api_hash`, session keys, proxy passwords or V2Ray links.
