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
14. Desktop notifications, unread app badge and Telegram dialog controls.
15. Per-chat drafts, message context menus, multi-selection and keyboard shortcuts.
16. Multi-file albums, drag-and-drop/paste attachments and recent emoji/sticker/GIF tools.
17. Safe account settings, local appearance preferences and connection diagnostics.
18. Connection recovery, packaged backend sidecar and reproducible Windows installer pipeline.

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

## Phase 13: notifications and dialog controls

The desktop shell now supports:

1. Opt-in native desktop notifications for incoming messages while another chat is open or the window is hidden.
2. Suppressing notifications for Telegram-muted conversations.
3. A total unread counter in the sidebar, document title and app badge where the desktop WebView supports it.
4. Opening the related conversation by selecting its desktop notification.
5. Pinning and unpinning a dialog through Telegram's dialog API.
6. Moving a dialog into or out of Telegram's archive folder.
7. Muting or unmuting a dialog through Telegram peer notification settings.
8. Live synchronization of dialog-state changes through the existing WebSocket.
9. An in-place nullable-safe local database migration for the muted state.

Notification permission is requested only after the user presses the notification control. Dashboard configuration, source sessions and proxy secrets remain read-only and are never returned to the frontend. Audio and video playback remains disabled.

## Phase 14: drafts and message workspace

The conversation workspace now supports:

1. Keeping a separate local draft for every Telegram conversation.
2. Restoring the original draft after editing or cancelling an existing message.
3. Opening a Telegram-style action menu by right-clicking a message.
4. Replying, reacting, forwarding, copying, selecting, editing or deleting from the context menu when allowed.
5. Selecting multiple messages and showing a dedicated selection toolbar.
6. Copying or forwarding multiple selected messages in chronological order.
7. Deleting multiple messages only when every selected message belongs to the current account.
8. Keyboard shortcuts: Ctrl/Cmd+F for chat search, Ctrl/Cmd+Enter to send, Delete for eligible selected messages and Escape to close the active layer.
9. Pure unit coverage for malformed, updated and removed local drafts.

Drafts are stored only in this client's local WebView storage and are never written to the dashboard. Multi-message actions reuse the existing guarded Telegram APIs. Audio and video playback remains disabled.

## Phase 15: attachments and expressive media

The composer now supports:

1. Queuing up to 10 local files and sending them through Telegram's album-capable upload flow.
2. Previewing image and GIF attachments, removing individual items or clearing the queue before upload.
3. Dragging files anywhere over the active conversation and dropping them into the composer queue.
4. Pasting images or GIFs directly from the clipboard into the composer.
5. Using an inline emoji picker that inserts at the current text cursor position.
6. Loading the account's recent Telegram stickers and saved GIFs without exposing document access hashes to the frontend.
7. Sending a recent sticker or GIF by an opaque local catalog identifier, including the active reply target.
8. Staging every upload only under `data/telegram_desktop/uploads`, enforcing Telegram's 10-item and 2 GB-per-file limits, and cleaning temporary files after success or failure.
9. Persisting and publishing every returned album message through the existing independent store and WebSocket flow.

The recent-media catalog lives only in backend memory and is rebuilt from the independently authorized Telegram client. Dashboard data remains read-only. Video and audio playback remains disabled; GIFs are treated as sendable media only.

## Phase 16: settings and account management

The settings surface now provides:

1. Safe account and independent-session status without exposing a phone number, authorization key or session path.
2. Redacted proxy/V2Ray route diagnostics from the existing read-only transport catalog.
3. A guarded logout action that removes only this client's independent session and leaves the dashboard source session untouched.
4. System, dark and light appearance modes stored only in local WebView preferences.
5. A compact conversation layout for smaller desktop windows.
6. A per-device automatic photo-loading preference; files remain explicit downloads.

Audio and video playback remains disabled. API credentials, proxy passwords, V2Ray links and dashboard session data are never returned to the frontend.

## Phase 17: production hardening and Windows installer

The release path now includes:

1. Exponential WebSocket reconnection with a full dialog and active-chat resync after interruption.
2. A backend connection monitor that rebuilds an authorized Telegram connection when Telethon is no longer connected.
3. A writable per-user client data root so an installed application never writes sessions, downloads or SQLite files under Program Files.
4. A PyInstaller entry point for a self-contained Python backend sidecar.
5. Tauri lifecycle management that starts the release sidecar and stops it when the desktop app exits.
6. A Windows GitHub Actions workflow that runs all tests, builds and smoke-tests the packaged sidecar, creates an unsigned current-user NSIS installer and uploads it as a workflow artifact.
7. A tag-driven release job that publishes the installer as a permanent GitHub Release asset for every `v*` tag.

The installer workflow is `.github/workflows/windows-installer.yml`. During active development it runs only for release branches matching `release/v*`, version tags matching `v*`, or a deliberate manual run. A version tag or release branch creates the matching tag and a permanent GitHub Release containing the installer executable. Normal pushes to `feature/telegram-desktop-foundation` run only the backend/frontend checks in `.github/workflows/development-ci.yml`; they do not build another installer.

The packaged backend reads optional secrets from `settings.env` inside Tauri's private per-user application data directory. The file is never bundled or committed. It may contain the same `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SOURCE_SESSION_PATH` and `TELEGRAM_PROXY_CONFIG` values already used locally; source-session and proxy catalog paths remain read-only.

For a local Windows release build:

1. Install the package dependencies with `python -m pip install -e ".[test,package]"`.
2. Build `app/desktop.py` with PyInstaller and copy the resulting executable to `frontend/src-tauri/binaries/telegram-desktop-backend-x86_64-pc-windows-msvc.exe`.
3. Run `npm run tauri build -- --config src-tauri/tauri.windows.conf.json` from `frontend`.

The standard development build does not auto-start a Python process; run the backend with Uvicorn during `npm run tauri dev`. Audio/video playback, calls and Stories remain outside this release.

## Local configuration

Copy .env.example to .env locally and fill in values without committing the file.

- TELEGRAM_SESSION_PATH: independent client session path.
- TELEGRAM_SOURCE_SESSION_PATH: optional source session path from the dashboard; read-only.
- TELEGRAM_PROXY_CONFIG: read-only proxy/route catalog, including existing local V2Ray routes.
- TELEGRAM_ALLOW_DIRECT: remains false unless direct fallback is deliberately enabled.

The frontend never receives api_hash, session keys, proxy passwords or V2Ray links.

## Windows development with PowerShell

Keep development on `feature/telegram-desktop-foundation`; installer releases can wait until the application is feature-complete.

From the repository root in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup-dev.ps1
notepad .env
.\scripts\run-dev.ps1
```

`setup-dev.ps1` requires Python 3.12, Node.js 22, Rust/Cargo and the normal Windows Tauri prerequisites. It creates an isolated `.venv`, installs the locked frontend dependencies, creates the ignored local `.env` file and runs the test/build checks. `run-dev.ps1` starts the FastAPI backend, waits for `/health`, opens the Tauri development window and stops the backend when the window exits.

The `.env` file must keep `TELEGRAM_SESSION_PATH` and `TELEGRAM_DATABASE_PATH` under this client's `data/telegram_desktop` directory. Dashboard session, proxy and V2Ray paths are read-only inputs and must never be copied into Git.
