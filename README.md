# Telegram Desktop

A standalone Windows Telegram-style desktop client built independently from the trading terminal.

## Goals

- Reuse the trading terminal's Telegram API configuration and proxy/V2Ray routes through a read-only local adapter.
- Keep an independent Telegram session and local chat/message database.
- Present accessible private chats, groups, channels, archived chats and folders in a Telegram Desktop-like interface.
- Load message history lazily and receive live updates.
- Show image/file messages; video and audio playback are intentionally deferred.
- Never commit .env, Telegram sessions, proxy secrets or V2Ray links.

The trading terminal remains a separate repository and its running session file is never opened for write by this project.

## Implemented foundation

1. Safe configuration and transport discovery.
2. Independent local session/database paths.
3. Dialog list, message history, send-text and live update API.
4. Telegram Desktop-style three-column UI shell.
5. Read-only media metadata and controlled media downloads.
6. Inline photo rendering; no video/audio playback.
7. Reply, edit-own-message and delete-own-message actions.
8. Server-side chat search and explicit-destination forwarding.

## Phase 2: controlled session bootstrap

When TELEGRAM_SOURCE_SESSION_PATH points to an existing Telethon .session file:

1. The backend reports IMPORT_READY instead of opening the source.
2. The user explicitly starts import from the UI or POST /api/telegram/session/import.
3. The source SQLite file is queried in read-only mode.
4. Only the authorization data needed to seed a new local session file is written under data/telegram_desktop.
5. The new session is connected through the read-only transport catalog.

TELEGRAM_AUTO_IMPORT_SOURCE is disabled by default. The app will not import a source session silently.

Important: this bootstrap creates a separate local session file, but it reuses the Telegram authorization key from the source. It is not a new Telegram device authorization. For a separate Telegram authorization, use the normal phone/code/2FA login flow instead.

## Phase 3: local phone/code/2FA login

If no source import is selected, the UI supports sending a Telegram login code, verifying the code, requesting the 2FA password when needed, and refreshing dialogs after authorization. Authentication errors are returned without logging phone numbers, codes, passwords or session values.

## Phase 4: dialogs, folders, unread and history paging

The client now supports:

1. Refreshing the live dialog list from Telegram.
2. Functional views for all chats, private chats, groups, channels and archived chats.
3. Showing unread counts from Telegram and marking a chat read when it is opened.
4. Loading older messages page by page with the existing independent local message store.

## Phase 5: photo display and controlled downloads

The client now supports:

1. Rendering photo messages inside the chat using the protected media endpoint.
2. Downloading photos, documents, audio and video through an explicit button.
3. Showing download progress state in the message card and retrying a failed download.
4. Caching completed downloads under the independent client data directory, which is ignored by Git.
5. Keeping audio/video playback disabled as requested.

The media endpoint re-fetches the exact Telegram message through the authorized independent client; it does not expose session values, API credentials, proxy settings or arbitrary filesystem paths.

## Phase 6: reply, edit and delete

The message workflow now supports:

1. Replying to any available message while preserving its Telegram reply reference.
2. Showing the referenced message inside the message bubble and jumping to it when it is loaded.
3. Editing text on the current account's own messages.
4. Deleting only the current account's own messages for everyone after confirmation.
5. Publishing local edit/delete events so the independent store and live UI stay synchronized.

The backend checks Telegram's outgoing-message flag before editing or deleting. Incoming messages cannot be changed through the local API.

## Phase 7: chat search and forwarding

The client now supports:

1. Server-side search inside the selected Telegram conversation.
2. A compact result panel with sender, snippet and timestamp.
3. Opening a result in the current message view and highlighting it.
4. Forwarding any available message through an explicit destination dialog.
5. Filtering the destination list by title or username.
6. Persisting forwarded messages in the target chat and publishing them through the existing WebSocket flow.

Search and forwarding use the authorized independent Telegram client. No dashboard database, source session, API hash or proxy secret is exposed to the frontend.

## Local configuration

Copy .env.example to .env locally and fill in values without committing the file.

- TELEGRAM_SESSION_PATH: independent client session path.
- TELEGRAM_SOURCE_SESSION_PATH: optional source session path from the dashboard; read-only.
- TELEGRAM_PROXY_CONFIG: read-only proxy/route catalog, including existing local V2Ray routes.
- TELEGRAM_ALLOW_DIRECT: remains false unless direct fallback is deliberately enabled.

The frontend never receives api_hash, session keys, proxy passwords or V2Ray links.
