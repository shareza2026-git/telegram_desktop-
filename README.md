# Telegram Desktop

A standalone Windows Telegram-style desktop client built independently from the trading terminal.

## Goals

- Reuse the trading terminal's Telegram API configuration and proxy/V2Ray routes through a read-only local adapter.
- Keep an independent Telegram session and local chat/message database.
- Present accessible private chats, groups, channels, archived chats and folders in a Telegram Desktop-like interface.
- Load message history lazily and receive live updates.
- Show image/file messages; video and audio playback are intentionally deferred.
- Never commit `.env`, Telegram sessions, proxy secrets or V2Ray links.

## Planned architecture

```
dashboard configuration (read-only)
        |
        v
transport/config adapter ---> independent Telegram client/session
                                      |
                                      v
                              chat/message store
                                      |
                         FastAPI + WebSocket API
                                      |
                              React + Tauri UI
```

The trading terminal remains a separate repository and its running session file is never opened for write by this project.

## Phase 1 scope

1. Safe configuration and transport discovery.
2. Independent account/session bootstrap.
3. Dialog list and live connection status.
4. Telegram Desktop-style three-column UI shell.
5. Separate chat/message API and WebSocket namespace.

## Security rules

- Secrets stay local and are read only by the backend.
- Session files are credentials and must remain outside Git.
- The frontend never receives `api_hash`, session strings, proxy passwords or V2Ray links.
- The application must not silently enable direct Telegram connectivity when configured routes fail.
