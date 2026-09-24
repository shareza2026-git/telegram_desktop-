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
9. Real chat/entity information and cached profile photos.
10. Safe photo/document sending with caption and reply support.
11. Standard Telegram message reactions with live synchronization.
12. Live typing presence and outgoing read receipts.
13. Telegram-style history navigation, unread boundary and pinned messages.

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

## Phase 8: chat information and avatars

The client now supports:

1. Reading safe Telegram entity metadata for the selected private chat, group, supergroup or channel.
2. Showing username, account status, member count when Telegram provides it, verification and safety flags.
3. Loading profile photos in the dialog list, chat header, forwarding dialog and information panel.
4. Falling back to the title initial when no profile photo is available.
5. Caching profile photos for one hour under data/telegram_desktop/avatars.

The profile API does not return phone numbers, API credentials, authorization keys, session paths or proxy configuration.

## Phase 9: send photos and files

The attachment button now supports:

1. Selecting a local photo or document from the desktop file picker.
2. Sending the current composer text as the Telegram caption.
3. Preserving the selected reply target when an attachment is sent.
4. Showing a visible upload state and preventing duplicate composer actions.
5. Rejecting empty files and files larger than 2 GB.
6. Staging the upload under data/telegram_desktop/uploads and deleting the temporary file after success or failure.
7. Publishing the returned Telegram message through the existing store and WebSocket path.

Audio and video files can be sent and downloaded, but playback remains disabled.

## Phase 10: message reactions

The message view now supports:

1. Reading standard emoji reaction counts from Telegram history and live messages.
2. Showing the current account's selected reaction distinctly.
3. Adding a reaction from a compact Telegram-style picker.
4. Removing the current account's reaction by selecting it again.
5. Refreshing the full message after a reaction change and publishing it through the existing WebSocket path.
6. Listening for Telegram reaction updates and synchronizing them into the independent local store.
7. Migrating existing local databases in place with a nullable reactions column.

Custom emoji and paid reactions are displayed only when Telegram exposes a standard emoji representation. Audio and video playback remains disabled.

## Phase 11: typing and read receipts

The live conversation view now supports:

1. Receiving Telegram typing, upload and recording actions through UserUpdate events.
2. Showing the active action in the selected chat header and expiring stale actions automatically.
3. Sending a rate-limited typing pulse while the local composer contains text.
4. Cancelling the typing action after inactivity, chat changes, editing mode or upload mode.
5. Receiving outbox MessageRead events and marking every eligible outgoing message as read.
6. Rendering one check for sent messages and two highlighted checks for messages read by the peer.
7. Persisting outgoing read state in the independent SQLite store with an in-place schema migration.

Typing presence is ephemeral and is not stored. Audio and video playback remains disabled.

## Phase 12: history navigation and pinned messages

The conversation view now supports:

1. Date separators between message days using the local display calendar.
2. A visible boundary at the first unread incoming message captured when a chat opens.
3. Automatic bottom-following only while the user is already near the latest messages.
4. A jump-to-bottom button with a counter for new incoming messages received below the viewport.
5. Loading older history without moving the user's current reading position.
6. Reading the chat's pinned message through Telegram and opening it from a compact header banner.
7. Caching the pinned message only in the independent local message store.

Pinned retrieval does not expose source-session data, API credentials or transport secrets. Audio and video playback remains disabled.

## Local configuration

Copy .env.example to .env locally and fill in values without committing the file.

- TELEGRAM_SESSION_PATH: independent client session path.
- TELEGRAM_SOURCE_SESSION_PATH: optional source session path from the dashboard; read-only.
- TELEGRAM_PROXY_CONFIG: read-only proxy/route catalog, including existing local V2Ray routes.
- TELEGRAM_ALLOW_DIRECT: remains false unless direct fallback is deliberately enabled.

The frontend never receives api_hash, session keys, proxy passwords or V2Ray links.
