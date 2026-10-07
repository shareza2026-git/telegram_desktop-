# Current Status

Checkpoint date: 2026-10-07

## Repository

Repository: `shareza2026-git/telegram_desktop-`

Authoritative development branch:

`feature/telegram-desktop-foundation`

Current approved/integrated development baseline before the pending release-architecture PR:

`0243352dbd9b41175998d1ecbc5cf21e7050f851`

Commit message:

`Fix NSIS PowerShell hook line endings`

## Current work

Work branch:

`work/release-tag-versioning`

Review:

PR #2 — `Make releases tag-driven and version-safe`

Status:

- release/version architecture implemented on work branch
- version manifests synchronized to baseline `0.1.25`
- tag-driven release helper added
- release CI made tag-authoritative
- project operating documentation being normalized into `AGENTS.md` + `docs/`
- development CI passing on the work branch

Do not merge PR #2 or create an official tag without explicit user authorization.

## Local directory model

Expected parent root:

`C:\Users\<USER>\Desktop\Desktop Telegram\`

Observed core directories:

- `dev\` — development Git working copy
- `live\` — intended last approved runnable version

The exact version currently present in `live\` has not been established in repository documentation. Do not infer it.

## Completed foundation

Major implemented areas include:

- independent Telegram desktop backend/frontend foundation
- dialogs/history/send/live updates
- media metadata/downloads and file sending
- reply/edit/delete/forward/search
- reactions/typing/read receipts/pins/unread navigation
- notifications/dialog controls/drafts
- multi-file attachments and recent expressive media
- account/settings/devices/profile surfaces
- recovery/packaged backend/Windows installer pipeline
- multi-instance Windows packaging behavior

## Current blockers / required follow-up

Before normal login on a new machine, session bootstrap paths need hardening so old portable/session state cannot be silently reused.

Before an official release, current npm vulnerability findings must be audited and classified.

See `docs/KNOWN_ISSUES.md`.

## Next intended phase

1. complete review/approval of PR #2;
2. integrate release/documentation architecture when authorized;
3. harden fresh-machine Telegram session behavior;
4. validate device naming/direct-connect policy;
5. perform dependency/security audit before release;
6. run release gate;
7. only then create the next version tag when explicitly authorized.

Expected next patch tag after `0.1.25`, if no newer valid tag exists:

`v0.1.26`

This is a target, not an authorization to publish.

## Deferred product scope

- audio/video playback
- calls
- Stories
- automatic updater

These remain deferred unless explicitly requested.
